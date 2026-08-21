arguments <- commandArgs(trailingOnly = TRUE)

if (length(arguments) != 2) {
  stop(paste(
    "Usage: Rscript scripts/glucose_simulator/run_simmodel.R",
    "<scenario-json> <output-directory>"
  ))
}

for (package in c("jsonlite", "ospsuite", "xml2")) {
  if (!requireNamespace(package, quietly = TRUE)) {
    stop(sprintf("The %s R package is not installed", package))
  }
}

if (!rSharp::dotnetAvailable()) {
  stop("The .NET runtime is not available to rSharp")
}

scenario_path <- normalizePath(arguments[[1]], mustWork = TRUE)
output_directory <- normalizePath(arguments[[2]], mustWork = TRUE)
scenario <- jsonlite::fromJSON(scenario_path, simplifyVector = FALSE)

require_fields <- function(value, fields, location) {
  missing <- setdiff(fields, names(value))
  if (length(missing) > 0) {
    stop(sprintf("Missing %s field(s): %s", location, paste(missing, collapse = ", ")))
  }
}

require_fields(
  scenario,
  c(
    "id",
    "model",
    "model_sha256",
    "steady_state",
    "simulation_time",
    "base_parameters",
    "runs",
    "outputs",
    "exposed_outputs",
    "verification"
  ),
  "scenario"
)

model_path <- normalizePath(scenario$model, mustWork = TRUE)

sha256 <- function(path) {
  output <- system2("sha256sum", path, stdout = TRUE, stderr = TRUE)
  status <- attr(output, "status")
  if (!is.null(status) && status != 0) {
    stop(sprintf("Could not calculate SHA-256 for %s", path))
  }
  strsplit(output[[1]], " ", fixed = TRUE)[[1]][[1]]
}

model_sha256 <- sha256(model_path)
if (model_sha256 != scenario$model_sha256) {
  stop(sprintf(
    "Model SHA-256 is %s, expected %s",
    model_sha256,
    scenario$model_sha256
  ))
}

assembly_path <- system.file("lib", "OSPSuite.SimModel.dll", package = "ospsuite")
if (assembly_path == "") {
  stop("OSPSuite.SimModel.dll is missing from the ospsuite installation")
}

suppressPackageStartupMessages(library(ospsuite))
invisible(rSharp::loadAssembly(assembly_path))

read_model <- function(path, grid) {
  require_fields(grid, c("start", "end", "step"), "time grid")
  values <- unlist(grid, use.names = FALSE)
  if (!all(vapply(values, is.numeric, logical(1))) || any(!is.finite(values))) {
    stop("Time grid values must be finite numbers")
  }
  if (grid$end <= grid$start || grid$step <= 0) {
    stop("Time grid requires end > start and step > 0")
  }

  intervals <- (grid$end - grid$start) / grid$step
  if (abs(intervals - round(intervals)) > .Machine$double.eps^0.5) {
    stop("Time grid range must be divisible by step")
  }

  document <- xml2::read_xml(path)
  interval <- xml2::xml_find_first(
    document,
    ".//*[local-name()='OutputSchema']/*[local-name()='OutputIntervalList']/*[local-name()='OutputInterval']"
  )
  if (inherits(interval, "xml_missing")) {
    stop("The model has no uniform OutputInterval")
  }

  xml2::xml_set_text(
    xml2::xml_find_first(interval, "./*[local-name()='StartTime']"),
    as.character(grid$start)
  )
  xml2::xml_set_text(
    xml2::xml_find_first(interval, "./*[local-name()='EndTime']"),
    as.character(grid$end)
  )
  xml2::xml_set_text(
    xml2::xml_find_first(interval, "./*[local-name()='NumberOfTimePoints']"),
    as.character(as.integer(round(intervals) + 1))
  )
  document
}

mark_persistable <- function(document, specifications) {
  for (index in seq_along(specifications)) {
    specification <- specifications[[index]]
    require_fields(specification, "path", sprintf("outputs[%d]", index))
    node <- xml2::xml_find_first(
      document,
      sprintf(
        ".//*[local-name()='V' or local-name()='Observer'][@path='%s']",
        specification$path
      )
    )
    if (inherits(node, "xml_missing")) {
      stop(sprintf("outputs[%d] references an unknown path: %s", index, specification$path))
    }
    xml2::xml_set_attr(node, "persistable", "1")
  }
}

EXPOSED_ID_BASE <- 900000

formula_of_parameter <- function(document, path, location) {
  node <- xml2::xml_find_first(
    document,
    sprintf(".//*[local-name()='P'][@path='%s']", path)
  )
  if (inherits(node, "xml_missing")) {
    stop(sprintf("%s references an unknown parameter path: %s", location, path))
  }
  formula <- xml2::xml_attr(node, "formulaId")
  if (is.na(formula)) {
    stop(sprintf("%s is a constant and cannot be observed: %s", location, path))
  }
  formula
}

formula_of_flux <- function(document, path, equation, location) {
  node <- xml2::xml_find_first(
    document,
    sprintf(".//*[local-name()='V'][@path='%s']", path)
  )
  if (inherits(node, "xml_missing")) {
    stop(sprintf("%s references an unknown species path: %s", location, path))
  }

  candidates <- xml2::xml_attr(
    xml2::xml_find_all(node, ".//*[local-name()='RHSFormula']"),
    "id"
  )
  equations <- vapply(candidates, function(id) {
    formula <- xml2::xml_find_first(
      document,
      sprintf(".//*[local-name()='ExplicitFormula'][@id='%s']/*[local-name()='Equation']", id)
    )
    if (inherits(formula, "xml_missing")) "" else xml2::xml_text(formula)
  }, character(1))

  matched <- candidates[equations == equation]
  if (length(matched) != 1) {
    stop(sprintf(
      "%s matched %d of the %d right-hand-side terms of %s",
      location,
      length(matched),
      length(candidates),
      path
    ))
  }
  matched[[1]]
}

expose_outputs <- function(document, specifications) {
  if (!is.list(specifications)) {
    stop("exposed_outputs must be a list")
  }
  if (length(specifications) == 0) {
    return(list())
  }

  observers <- xml2::xml_find_first(document, ".//*[local-name()='ObserverList']")
  if (inherits(observers, "xml_missing")) {
    stop("The model has no ObserverList")
  }

  lapply(seq_along(specifications), function(index) {
    specification <- specifications[[index]]
    location <- sprintf("exposed_outputs[%d]", index)
    require_fields(specification, c("variable", "unit"), location)

    locators <- intersect(c("parameter", "species"), names(specification))
    if (length(locators) != 1) {
      stop(sprintf("%s must declare exactly one of parameter or species", location))
    }

    if (locators == "parameter") {
      source <- specification$parameter
      formula <- formula_of_parameter(document, source, location)
    } else {
      require_fields(specification, "equation", location)
      source <- specification$species
      formula <- formula_of_flux(document, source, specification$equation, location)
    }

    id <- EXPOSED_ID_BASE + index
    entity_id <- sprintf("exposed-%d", id)
    path <- sprintf("%s|Exposed|%s", source, specification$variable)

    observer <- xml2::xml_add_child(observers, "Observer")
    xml2::xml_set_attr(observer, "id", as.character(id))
    xml2::xml_set_attr(observer, "entityId", entity_id)
    xml2::xml_set_attr(observer, "name", specification$variable)
    xml2::xml_set_attr(observer, "path", path)
    xml2::xml_set_attr(observer, "unit", specification$unit)
    xml2::xml_set_attr(observer, "persistable", "1")
    xml2::xml_set_attr(observer, "formulaId", formula)

    list(
      variable = specification$variable,
      id = id,
      entity_id = entity_id,
      path = path,
      unit = specification$unit
    )
  })
}

without_root <- function(paths) {
  sub("^[^|]+[|]", "", paths)
}

entity_table <- function(document, element, explicit_only = FALSE) {
  predicate <- if (explicit_only) "[@value]" else ""
  nodes <- xml2::xml_find_all(
    document,
    sprintf(".//*[local-name()='%s']%s", element, predicate)
  )
  data.frame(
    path = without_root(xml2::xml_attr(nodes, "path")),
    entity_id = xml2::xml_attr(nodes, "entityId"),
    stringsAsFactors = FALSE
  )
}

overrides <- function(entries, location) {
  if (!is.list(entries)) {
    stop(sprintf("%s must be a list", location))
  }
  if (length(entries) == 0) {
    return(setNames(numeric(), character()))
  }

  paths <- values <- vector("list", length(entries))
  for (index in seq_along(entries)) {
    require_fields(entries[[index]], c("path", "value"), sprintf("%s[%d]", location, index))
    path <- entries[[index]]$path
    value <- entries[[index]]$value
    if (!is.character(path) || length(path) != 1 || path == "") {
      stop(sprintf("%s[%d].path must be a non-empty string", location, index))
    }
    if (!is.numeric(value) || length(value) != 1 || !is.finite(value)) {
      stop(sprintf("%s[%d].value must be a finite number", location, index))
    }
    paths[[index]] <- path
    values[[index]] <- value
  }

  paths <- unlist(paths, use.names = FALSE)
  if (anyDuplicated(paths)) {
    stop(sprintf("%s contains duplicate paths", location))
  }
  setNames(as.numeric(unlist(values, use.names = FALSE)), paths)
}

merge_overrides <- function(base, additional) {
  combined <- c(base, additional)
  combined[!duplicated(names(combined), fromLast = TRUE)]
}

net_objects <- function(simulation, property, document, element, paths) {
  if (length(paths) == 0) {
    return(list())
  }

  table <- entity_table(document, element)
  objects <- simulation$get(property)$call("ToArray")
  if (length(objects) != nrow(table)) {
    stop(sprintf(
      "%s exposes %d objects, but the XML contains %d %s nodes",
      property,
      length(objects),
      nrow(table),
      element
    ))
  }

  indices <- match(paths, table$path)
  if (anyNA(indices)) {
    stop(sprintf(
      "Unknown %s path(s): %s",
      element,
      paste(paths[is.na(indices)], collapse = ", ")
    ))
  }

  selected <- objects[indices]
  actual <- vapply(selected, function(object) object$get("Path"), character(1))
  if (!identical(unname(actual), unname(paths))) {
    stop(sprintf("%s object order does not match the model XML", property))
  }
  selected
}

register_objects <- function(simulation, property, objects) {
  if (length(objects) == 0) {
    return(invisible(NULL))
  }
  selected <- simulation$get(property)
  for (object in objects) {
    invisible(selected$call("Add", object))
  }
  invisible(simulation$set(property, selected))
}

prepare_simulation <- function(document, parameter_values, species_values) {
  simulation <- rSharp::newObjectFromName("OSPSuite.SimModel.Simulation")
  invisible(simulation$call("LoadFromXMLString", as.character(document)))

  parameter_objects <- net_objects(
    simulation,
    "ParameterProperties",
    document,
    "P",
    names(parameter_values)
  )
  species_objects <- net_objects(
    simulation,
    "SpeciesProperties",
    document,
    "V",
    names(species_values)
  )
  register_objects(simulation, "VariableParameters", parameter_objects)
  register_objects(simulation, "VariableSpecies", species_objects)
  invisible(simulation$call("FinalizeSimulation"))

  for (index in seq_along(parameter_objects)) {
    invisible(parameter_objects[[index]]$set("Value", unname(parameter_values[[index]])))
  }
  if (length(parameter_objects) > 0) {
    invisible(simulation$call("SetParameterValues"))
  }

  for (index in seq_along(species_objects)) {
    invisible(species_objects[[index]]$set("InitialValue", unname(species_values[[index]])))
  }
  if (length(species_objects) > 0) {
    invisible(simulation$call("SetSpeciesValues"))
  }
  simulation
}

run_steady_state <- function(document, parameter_values) {
  simulation <- prepare_simulation(document, parameter_values, setNames(numeric(), character()))
  on.exit(invisible(simulation$call("Dispose")), add = TRUE)
  invisible(simulation$call("RunSimulation"))

  species <- entity_table(document, "V", explicit_only = TRUE)
  final_values <- vapply(species$entity_id, function(entity_id) {
    values <- simulation$call("ValuesFor", entity_id)$get("Values")
    tail(values, 1)
  }, numeric(1))
  if (any(!is.finite(final_values))) {
    stop("The steady-state simulation produced non-finite species values")
  }
  setNames(final_values, species$path)
}

extract_outputs <- function(simulation, run_id, outputs) {
  times <- simulation$get("SimulationTimes")
  frames <- lapply(outputs, function(specification) {
    require_fields(
      specification,
      c("variable", "id", "entity_id", "path", "unit"),
      "output specification"
    )
    if (!is.numeric(specification$id) || length(specification$id) != 1) {
      stop("Every output id must be numeric")
    }

    output <- simulation$call("ValuesFor", as.integer(specification$id))
    values <- output$get("Values")
    if (length(values) != length(times)) {
      stop(sprintf(
        "Output %d has %d values for %d simulation times",
        specification$id,
        length(values),
        length(times)
      ))
    }
    if (any(!is.finite(values))) {
      stop(sprintf("Output %d contains non-finite values", specification$id))
    }
    if (output$get("EntityId") != specification$entity_id) {
      stop(sprintf("Output %d entity ID does not match the scenario", specification$id))
    }
    if (output$get("Path") != specification$path) {
      stop(sprintf("Output %d path does not match the scenario", specification$id))
    }

    data.frame(
      run = run_id,
      time = times,
      variable = specification$variable,
      output_id = as.integer(specification$id),
      entity_id = output$get("EntityId"),
      path = output$get("Path"),
      name = output$get("Name"),
      unit = specification$unit,
      value = values,
      stringsAsFactors = FALSE
    )
  })
  do.call(rbind, frames)
}

run_case <- function(document, run, base_parameters, steady_state_values, outputs) {
  require_fields(run, c("id", "parameters"), "run")
  run_parameters <- overrides(run$parameters, sprintf("run %s parameters", run$id))
  parameter_values <- merge_overrides(base_parameters, run_parameters)
  simulation <- prepare_simulation(document, parameter_values, steady_state_values)
  on.exit(invisible(simulation$call("Dispose")), add = TRUE)
  invisible(simulation$call("RunSimulation"))
  extract_outputs(simulation, run$id, outputs)
}

require_fields(scenario$steady_state, c("time"), "steady_state")
base_parameters <- overrides(scenario$base_parameters, "base_parameters")
steady_document <- read_model(model_path, scenario$steady_state$time)
cat(sprintf("Running %s steady state\n", scenario$id))
steady_state_values <- run_steady_state(steady_document, base_parameters)

simulation_document <- read_model(model_path, scenario$simulation_time)
mark_persistable(simulation_document, scenario$outputs)
exposed <- expose_outputs(simulation_document, scenario$exposed_outputs)
outputs <- c(scenario$outputs, exposed)
cat(sprintf(
  "Exporting %d model outputs and %d exposed parameters\n",
  length(scenario$outputs),
  length(exposed)
))

trajectories <- do.call(rbind, lapply(scenario$runs, function(run) {
  cat(sprintf("Running %s/%s\n", scenario$id, run$id))
  run_case(
    simulation_document,
    run,
    base_parameters,
    steady_state_values,
    outputs
  )
}))

if (length(scenario$runs) != 1) {
  stop("Scenario must declare exactly one run")
}

summary_rows <- lapply(split(trajectories, trajectories$variable), function(values) {
  values <- values[order(values$time), ]
  deviation <- values$value - values$value[[1]]
  max_index <- which.max(deviation)
  min_index <- which.min(deviation)
  data.frame(
    variable = values$variable[[1]],
    baseline = values$value[[1]],
    max_deviation = deviation[[max_index]],
    max_deviation_time = values$time[[max_index]],
    min_deviation = deviation[[min_index]],
    min_deviation_time = values$time[[min_index]],
    stringsAsFactors = FALSE
  )
})
summary <- do.call(rbind, summary_rows)
row.names(summary) <- NULL

for (check in scenario$verification) {
  require_fields(check, c("variable", "metric", "comparison", "threshold"), "verification")
  row <- summary[summary$variable == check$variable, ]
  if (nrow(row) != 1) {
    stop(sprintf("Verification variable is not an output: %s", check$variable))
  }
  if (!check$metric %in% c("max_deviation", "min_deviation")) {
    stop(sprintf("Unknown verification metric: %s", check$metric))
  }
  value <- row[[check$metric]][[1]]
  passed <- switch(
    check$comparison,
    greater_than = value > check$threshold,
    less_than = value < check$threshold,
    stop(sprintf("Unknown verification comparison: %s", check$comparison))
  )
  if (!passed) {
    stop(sprintf(
      "Verification failed: %s %s is %.15g, expected %s %.15g",
      check$variable,
      check$metric,
      value,
      check$comparison,
      check$threshold
    ))
  }
}

write.csv(trajectories, file.path(output_directory, "trajectories.csv"), row.names = FALSE)
write.csv(summary, file.path(output_directory, "response_summary.csv"), row.names = FALSE)

manifest <- list(
  scenario_id = scenario$id,
  scenario_path = scenario_path,
  model_path = model_path,
  model_sha256 = model_sha256,
  generated_at = format(Sys.time(), tz = "UTC", usetz = TRUE),
  runtime = list(
    R = R.version.string,
    ospsuite = as.character(packageVersion("ospsuite")),
    rSharp = as.character(packageVersion("rSharp"))
  ),
  steady_state_species = length(steady_state_values),
  rows = nrow(trajectories),
  scenario = scenario
)
jsonlite::write_json(
  manifest,
  file.path(output_directory, "manifest.json"),
  auto_unbox = TRUE,
  digits = NA,
  pretty = TRUE,
  null = "null"
)

cat(sprintf(
  "Completed %s: %d steady-state species, %d trajectory rows, %s\n",
  scenario$id,
  length(steady_state_values),
  nrow(trajectories),
  output_directory
))

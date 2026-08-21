arguments <- commandArgs(trailingOnly = TRUE)

if (length(arguments) != 1) {
  stop(paste(
    "Usage: Rscript scripts/glucose_simulator/install_ospsuite.R",
    "<ospsuite-version>"
  ))
}

requested_version <- arguments[[1]]
repositories <- c(
  OSP = "https://open-systems-pharmacology.r-universe.dev",
  CRAN = "https://cloud.r-project.org"
)
available <- available.packages(repos = repositories)

if (!"ospsuite" %in% rownames(available)) {
  stop("ospsuite is not available from the configured repositories")
}

available_version <- available["ospsuite", "Version"]

if (available_version != requested_version) {
  stop(sprintf(
    "Requested ospsuite %s, but the stable repository provides %s",
    requested_version,
    available_version
  ))
}

if (requireNamespace("ospsuite", quietly = TRUE)) {
  installed_version <- as.character(packageVersion("ospsuite"))

  if (installed_version == requested_version) {
    cat(sprintf("ospsuite %s is already installed\n", installed_version))
    quit(status = 0)
  }
}

options(repos = repositories)
install.packages("ospsuite")
installed_version <- as.character(packageVersion("ospsuite"))

if (installed_version != requested_version) {
  stop(sprintf(
    "Installed ospsuite %s instead of requested %s",
    installed_version,
    requested_version
  ))
}

cat(sprintf("Installed ospsuite %s\n", installed_version))

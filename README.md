# organ-agents

## Vision

organ-agents is a research system for building mechanistic, whole-body models of physiology with collaborating AI agents. Its long-term purpose is to help turn biological evidence into testable clinical hypotheses: explain how an intervention changes the body, identify the most consequential downstream effects, and prioritize predictions for expert or experimental validation.

## Core idea

Physiology is distributed: a perturbation first changes molecular or cellular processes in one location, then propagates through endocrine, immune, neural, and vascular communication, producing remote-organ and whole-body phenotypes. A useful model must preserve this locality while making cross-organ causality explicit.

Each organ or tissue agent therefore owns a constrained local vocabulary of states, mechanisms, and outputs. Shared Blood translates declared local outputs into circulating signals. Starting from an intervention or physiological perturbation, the system reconstructs a canonical causal graph across these boundaries. The graph is inspectable, comparable with ground truth, and suitable for evidence-based critique rather than being a free-form explanation.

## Research roadmap

### Phase 1: Recover established pathways

The immediate goal is to faithfully reproduce classic physiological pathways and mechanistic simulators from textbooks and established literature. This phase evaluates whether the system can select the right components, preserve causal direction, represent feedback and parallel branches, and recover known whole-body responses from a defined perturbation.

Success here establishes a reliable substrate: local agent boundaries, shared representations, evaluation graphs, and failure analysis must all work before asking the system to reason beyond known answers.

### Phase 2: Extend beyond the knowledge cutoff

Once the system can recover established mechanisms, it should incorporate post-cutoff research and identify mechanistic updates that a static model would miss. The objective is not merely to retrieve newer papers, but to connect new findings to the existing causal model and determine their consequences across organs and scales.

Candidate discoveries should be traceable to their supporting evidence, distinguish inference from observation, and state the conditions under which they are expected to hold.

### Phase 3: Generate and validate novel hypotheses

The longer-term ambition is to propose plausible, previously unreported findings: a local molecular or cellular effect that propagates through tissue and systemic communication into a distinctive whole-body outcome. These hypotheses must be explicit enough for clinicians and experimentalists to assess, falsify, and validate.

## Toward virtual clinical trials

This framework supports virtual clinical trials. A model can represent how a drug or intervention changes a local mechanism, trace the resulting cross-organ cascade, and surface candidate benefits, risks, biomarkers, or phenotypes. The aim is not to replace clinical judgment or experiments, but to make mechanistic reasoning more systematic and to focus real-world validation on the most informative hypotheses.

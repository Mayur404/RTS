# Research status

The current prototype is a finite paired discrete-event experiment for distributed
real-time workflows. It has actual neural inference, private SGD/FedAvg, resource
and radio accounting, monitored remote attempts and conditionally admitted local
early exits. Runtime identities, canonical events and integer-microsecond time are
shared by metrics and evidence. At most one task result can commit.

The facility UI has only Simulation and Results. Travel is illustrative; CPU/GPU,
tasks, transfers and outcomes use actual simulation records. The result summary
separates fallback-task completion, prevented workflow misses and protected-only
regressions. A recovery does not imply whole-workflow success.

Use [research methods](docs/research_methods.md), [publication scope](docs/publication_readiness_review.md)
and [the project review](docs/project_review.md). The [final LaTeX/PDF](docs/README.md)
separates implementation, archived model evaluation and planned timing studies.

Custom fleet/workload calibration remains unvalidated. Physical RF, perception,
motion and safety are not established. Host latency is measured separately from
configured service budgets and does not prove a hardware WCET. Finite tests and
audits establish their recorded scope, not universal correctness.

New experiments write raw events, manifests, source/model archives and metrics
under `.validation/`. These generated records and local historical backups are
ignored by Git. The repository ships runtime model bundles and code to generate
fresh evidence; an ordinary clone does not include the author's historical raw
training traces or developer audit runs. Preserve each artifact's original source,
configuration and checksum when using it as evidence.

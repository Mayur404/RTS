# 0018: Recorded inference graphs and decision explanations

Status: accepted. Owner: primary agent.

The graph shown as a GNN input must be the tensor topology actually passed to the model, at its recorded decision timestamp. PREDICTION adds an optional `graph` with the unchanged research-task-resource/9-v3 feature schema, node identities/kinds, float32 feature rows, int64 edge_index and queried-node index. The tensor byte digest remains `graph_sha256`. Self loops remain part of the model input even when visually omitted. Task-resource associations are model edges, not proof of physical allocation; allocation remains owned by RESOURCE_SAMPLE.

DECISION adds the actual neural threshold and booleans for neural risk, local-deadline pressure and end-to-end pressure, plus the configured deadline margin. These are observations of the existing decision rule, not changes to scheduling or model weights. Older records without these additions remain readable; graphs unavailable in older records are explicitly labeled.

An independent audit reconstructs float32/int64 bytes from a recorded graph and checks its digest, dimensions, vertex identities, queried-task binding and edge endpoints. Dashboard graph inspection and the decision route use these canonical records. Analytical RTA remains a separate fixed-priority reference; neither graph edges nor admission predictions constitute its certificate.

No configuration, model bundle, event-envelope or feature-schema version changes. New fields are additive. New evidence retains its own source/manifest identity; frozen study artifacts remain unchanged.

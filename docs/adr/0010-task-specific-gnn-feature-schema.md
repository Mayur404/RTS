# ADR 0010: Task-specific GNN feature schema

## Status

Accepted.

## Context

The first graph schema had eight features and pooled one representation for a
whole device. Runtime calls for different tasks on the same device therefore
received the same learned prediction. Rollout labels likewise represented any
critical miss on the device rather than the task being scored.

## Decision

Feature schema `hetero-task-resource/9-v2` adds a binary focus-task feature.
Runtime graph construction marks the task passed to the predictor. Dataset
generation emits one sample per active critical task and labels only that
task's future deadline outcome within the configured lookahead window.

Saved weights from the eight-feature schema are incompatible. The bundle
loader requires an integrity-checked bundle declaring the new schema.

## Consequences

Predictions can vary by task state while retaining shared resource and
contention context. A model must be retrained before it can be used by the
explicit GNN experiment policy.

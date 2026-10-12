"""Auditable analytical reference, separate from dynamic execution."""
from fastapi.encoders import jsonable_encoder
from rts_predictive.verification.models import FixedPriorityTask,CertificateBinding,AnalysisAssumptions,AnalysisProvenance
from rts_predictive.verification.timing_analyzer import TimingAnalyzer
from rts_predictive.simulator.research_engine import ceil_div


def control_partition_reference(config,source):
    """Hypothetical isolated FP partition: does not certify dynamic EDF/GPU."""
    workflow=next((w for w in config.workflows if w.pipeline_id=='control'),None)
    if workflow is None:return {'evidence':'ANALYTICAL','scope':'isolated_control_reference','certificates':[]}
    certificates=[]
    for device in config.devices:
        background=max((f.cpu_ppm for f in config.faults if f.device_id==device.device_id),default=0)
        rate=device.cpu_speed_ppm*max(10000,1000000-background-150000)//1000000*450000//1000000
        tasks=tuple(FixedPriorityTask(t.task_id,t.period_us,t.relative_deadline_us,
                    ceil_div(t.wcet_distribution.wcet_us*1000000,rate),t.priority,
                    jitter_us=workflow.end_to_end_deadline_us,
                    overhead_us=ceil_div(config.dispatch_cost_us*1000000,rate),
                    wcet_evidence='CONFIGURED_SIMULATION_BOUND_NOT_HARDWARE_WCET') for t in workflow.tasks)
        binding=CertificateBinding(scenario_hash=config.config_hash,scheduler_config_hash='isolated-fp-control-reference-v1',
                    hardware_profile_hash=device.config_hash,resource_partition_id=device.device_id+'/hypothetical-control',
                    fallback_mode_id='NONE_REFERENCE_ONLY')
        assumptions=AnalysisAssumptions(additional=('hypothetical CPU reservation at declared minimum rate',
                    'independent control-stage release overapproximation with e2e jitter',
                    'excludes autonomy, telemetry, watchdog, inference, FL and network',
                    'does not certify the dynamic EDF/GPU/offload simulator'))
        certificate=TimingAnalyzer.analyze_task_set(tasks,binding=binding,assumptions=assumptions,
                    provenance=AnalysisProvenance(code_revision=source.get('code_revision') or 'UNKNOWN',
                                                  source_artifact_hashes=(source['source_sha256'],)))
        certificates.append({'device':device.device_id,'reserved_rate_ppm':rate,'certificate':jsonable_encoder(certificate)})
    return {'evidence':'ANALYTICAL','scope':'hypothetical_isolated_fixed_priority_control_partition',
            'applies_to_live_scheduler':False,'certificates':certificates}

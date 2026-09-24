"""Research artifact entry point backed by canonical simulation events."""


def generate_all_research_artifacts(output_dir="results"):
    from scripts.generate_paper_artifacts import generate_paper_artifacts

    index = generate_paper_artifacts(
        output_dir=f"{output_dir}/paper",
        plots_dir=f"{output_dir}/plots",
    )
    return {"figures": index["figures"], "tables": [index["table"]]}

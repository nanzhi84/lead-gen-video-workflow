from __future__ import annotations

from packages.production.pipeline import get_digital_human_workflow


def main() -> None:
    workflow = get_digital_human_workflow()
    node_count = len(workflow.template.nodes)
    print(f"Cutagent worker ready: {workflow.template.workflow_template_id}@{workflow.template.version}")
    print(f"Registered activity contracts: {node_count}")


if __name__ == "__main__":
    main()


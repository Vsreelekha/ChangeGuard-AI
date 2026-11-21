export type WorkflowStageStatus =
  | "Pending"
  | "In Progress"
  | "Completed"
  | "Failed";

type Props = {
  analysisStatus: WorkflowStageStatus;
  selectionStatus: WorkflowStageStatus;
  executionStatus: WorkflowStageStatus;
  riskStatus: WorkflowStageStatus;
};

function WorkflowStatus({
  analysisStatus,
  selectionStatus,
  executionStatus,
  riskStatus,
}: Props) {
  const stages = [
    {
      name: "Code Analysis",
      status: analysisStatus,
    },
    {
      name: "Test Selection",
      status: selectionStatus,
    },
    {
      name: "Test Execution",
      status: executionStatus,
    },
    {
      name: "Risk Assessment",
      status: riskStatus,
    },
  ];

  return (
    <section className="workflow-status">
      <h2>Workflow Status</h2>

      <div className="workflow-list">
        {stages.map((stage) => (
          <div
            className={`workflow-item status-${stage.status
              .toLowerCase()
              .replace(" ", "-")}`}
            key={stage.name}
          >
            <p>{stage.name}</p>
            <strong>{stage.status}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}

export default WorkflowStatus;

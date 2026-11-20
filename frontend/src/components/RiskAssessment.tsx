type RiskData = {
  risk_level: "Low" | "Medium" | "High";
  risk_reason: string;
  deployment_recommendation: string;
};

type Props = {
  risk: RiskData;
};

function RiskAssessment({ risk }: Props) {
  const riskClass = risk.risk_level.toLowerCase();

  return (
    <section className="risk-section">
      <h2>Risk Assessment</h2>

      <div className={`risk-card ${riskClass}`}>
        <h3>{risk.risk_level} Risk</h3>

        <p>{risk.risk_reason}</p>

        <div className="recommendation">
          <strong>Deployment Recommendation</strong>
          <p>{risk.deployment_recommendation}</p>
        </div>
      </div>
    </section>
  );
}

export default RiskAssessment;

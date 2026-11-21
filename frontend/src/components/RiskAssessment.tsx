import type { RiskAssessment as BackendRiskAssessment } from "../services/api";

type Props = { risk: BackendRiskAssessment };

function RiskAssessment({ risk }: Props) {
  const level = risk.level.toLowerCase();
  return (
    <section className="risk-section">
      <h2>Risk Assessment</h2>
      <div className={`risk-card risk-card-${level}`}>
        <h3>{risk.level} Risk · {risk.score}/100</h3>
        <p>{risk.recommendation}</p>
        <p className="field-note">Verification: {risk.verification_status}</p>
      </div>
    </section>
  );
}

export default RiskAssessment;

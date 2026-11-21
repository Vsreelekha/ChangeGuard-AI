import type { PageName } from "./Sidebar";

type Props = {
  activePage: PageName;
};

function Header({ activePage }: Props) {
  return (
    <header className="header">
      <div>
        <p className="eyebrow">CHANGEGUARD AI WORKSPACE</p>
        <h2>{activePage}</h2>
        <p>Risk-based regression testing for every change.</p>
      </div>

      <div className="workspace-badge">
        <span className="workspace-avatar" aria-hidden="true">CG</span>
        <span>Development Workspace</span>
      </div>
    </header>
  );
}

export default Header;

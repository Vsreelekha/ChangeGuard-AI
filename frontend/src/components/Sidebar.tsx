import {
  LayoutDashboard,
  Code2,
  ListChecks,
  ClipboardCheck,
  ShieldCheck,
} from "lucide-react";

export type PageName =
  | "Dashboard"
  | "Code Analysis"
  | "Test Selection"
  | "Test Results"
  | "Risk Report";

type SidebarProps = {
  activePage: PageName;
  setActivePage: (page: PageName) => void;
  isOpen: boolean;
};

function Sidebar({ activePage, setActivePage, isOpen }: SidebarProps) {
  const menuItems = [
    { name: "Dashboard", icon: LayoutDashboard },
    { name: "Code Analysis", icon: Code2 },
    { name: "Test Selection", icon: ListChecks },
    { name: "Test Results", icon: ClipboardCheck },
    { name: "Risk Report", icon: ShieldCheck },
  ] as const;

  return (
    <aside
      className={`sidebar ${isOpen ? "sidebar-open" : ""}`}
      id="primary-navigation"
    >
      <div className="brand-lockup">
        <span className="brand-mark" aria-hidden="true">C</span>
        <div>
          <h2 className="brand">ChangeGuard</h2>
          <p>AI REGRESSION GUARD</p>
        </div>
      </div>

      <p className="sidebar-label">WORKSPACE</p>

      <nav aria-label="Primary navigation">
        {menuItems.map((item) => {
          const Icon = item.icon;

          return (
            <button
              key={item.name}
              className={
                activePage === item.name ? "nav-item active" : "nav-item"
              }
              onClick={() => setActivePage(item.name)}
              aria-current={activePage === item.name ? "page" : undefined}
            >
              <Icon size={19} />
              <span>{item.name}</span>
            </button>
          );
        })}
      </nav>
    </aside>
  );
}

export default Sidebar;

import { useEffect, useState } from "react";
import { Button, Layout, Menu, Space, Tag, Tooltip, theme } from "antd";
import {
  AppstoreOutlined,
  BulbOutlined,
  DashboardOutlined,
  MessageOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  MoonOutlined,
  ProjectOutlined,
  SearchOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAppStore } from "../store/appStore";
import { selectedGlobalKey } from "./layout/navigation";
import { useTheme } from "../state/theme";

const { Header, Sider, Content } = Layout;

const globalNavigation = [
  { key: "/", icon: <DashboardOutlined />, label: "首页" },
  { key: "/workspaces", icon: <ProjectOutlined />, label: "课题空间" },
  { key: "/search", icon: <SearchOutlined />, label: "论文检索" },
  { key: "/chat", icon: <MessageOutlined />, label: "AI 助手" },
];

export default function AppLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const { token } = theme.useToken();
  const { isDark, toggleTheme } = useTheme();
  const [collapsed, setCollapsed] = useState(false);
  const [mobile, setMobile] = useState(false);
  const currentWorkspaceId = useAppStore((state) => state.currentWorkspaceId);
  const currentWorkspaceName = useAppStore((state) => state.currentWorkspaceName);

  useEffect(() => {
    if (!mobile) setCollapsed(false);
  }, [mobile]);

  const items = globalNavigation.map((item) => ({
    ...item,
    onClick: () => {
      navigate(item.key);
      if (mobile) setCollapsed(true);
    },
  }));

  return (
    <Layout className="gm-app-layout">
      <Sider
        width={232}
        breakpoint="lg"
        collapsedWidth={0}
        collapsed={collapsed}
        trigger={null}
        onBreakpoint={setMobile}
        className="gm-sider"
        style={{ background: token.colorBgContainer }}
      >
        <div className="gm-brand">
          <div className="gm-brand-mark"><AppstoreOutlined /></div>
          <div>
            <strong>GapMind</strong>
            <span>Research workspace</span>
          </div>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[selectedGlobalKey(location.pathname)]}
          items={items}
          style={{ borderRight: 0 }}
        />
        <div className="gm-sider-footer">
          <Tag color="blue">证据驱动研究</Tag>
          <TypographyFooter />
        </div>
      </Sider>
      <Layout>
        <Header className="gm-topbar" style={{ background: token.colorBgContainer }}>
          <Space size="middle">
            {mobile && (
              <Button
                type="text"
                aria-label={collapsed ? "打开导航" : "关闭导航"}
                icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
                onClick={() => setCollapsed((value) => !value)}
              />
            )}
            <span className="gm-topbar-title">围绕课题推进研究</span>
          </Space>
          <Space size="small" wrap>
            <Tooltip title={currentWorkspaceName || "进入课题空间后查看处理任务"}>
              <Button
                type="text"
                icon={<ThunderboltOutlined />}
                onClick={() => navigate(currentWorkspaceId ? `/workspaces/${currentWorkspaceId}/activity` : "/workspaces")}
              >
                处理中心
              </Button>
            </Tooltip>
            <Button type="text" icon={<ProjectOutlined />} onClick={() => navigate("/workspaces")}>
              切换课题
            </Button>
            <Tooltip title={isDark ? "切换到浅色模式" : "切换到深色模式"}>
              <Button type="text" aria-label="切换主题" icon={isDark ? <BulbOutlined /> : <MoonOutlined />} onClick={toggleTheme} />
            </Tooltip>
          </Space>
        </Header>
        <Content className="gm-content">
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}

function TypographyFooter() {
  return <span className="gm-sider-caption">从文献到可验证的研究机会</span>;
}

import { Component, type ErrorInfo, type ReactNode } from "react";
import { Button, Result, Space } from "antd";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
}

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): Partial<State> {
    return { hasError: true };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    // eslint-disable-next-line no-console
    console.error("ErrorBoundary caught:", error, errorInfo);
  }

  handleReload = () => {
    this.setState({ hasError: false });
    window.location.reload();
  };

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <Result
          status="error"
          title="页面暂时无法显示"
          subTitle="现有研究数据不会因此被修改。请重新加载；若问题持续，请先返回首页再进入相应功能。"
          extra={
            <Space>
              <Button type="primary" onClick={this.handleReload}>重新加载</Button>
              <Button href="/">返回首页</Button>
            </Space>
          }
        />
      );
    }
    return this.props.children;
  }
}

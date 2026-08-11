"use client";
import { Component, ErrorInfo, ReactNode } from "react";

export default class ErrorBoundary extends Component<{ children: ReactNode; fallback?: ReactNode }> {
  state = { hasError: false, error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { hasError: true, error }; }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[ErrorBoundary]", error.message, info?.componentStack);
  }
  render() {
    if (this.state.hasError)
      return this.props.fallback || (
        <div className="empty-state" style={{ padding: 40, textAlign: "center" }}>
          <p>페이지를 불러오는 중 오류가 발생했습니다.</p>
          <button className="btn btn-primary" style={{ marginTop: 12 }} onClick={() => this.setState({ hasError: false })}>다시 시도</button>
        </div>
      );
    return this.props.children;
  }
}

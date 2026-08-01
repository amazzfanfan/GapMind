import { useState } from "react";
import { Button, Input, Space, Typography } from "antd";
import { SendOutlined } from "@ant-design/icons";
import { shouldSendOnEnter } from "../../pages/chatState";

export default function ChatComposer({ loading, onSend, value, onChange }: { loading: boolean; onSend: (value: string) => void; value: string; onChange: (value: string) => void }) {
  const [focused, setFocused] = useState(false);
  const send = () => { const content = value.trim(); if (!content || loading) return; onSend(content); };
  return <div className={`gm-chat-composer ${focused ? "is-focused" : ""}`}><Input.TextArea value={value} autoSize={{ minRows: 1, maxRows: 7 }} maxLength={12000} placeholder="输入你的问题…" aria-label="输入消息" onFocus={() => setFocused(true)} onBlur={() => setFocused(false)} onChange={(event) => onChange(event.target.value)} onKeyDown={(event) => { if (shouldSendOnEnter(event)) { event.preventDefault(); send(); } }} /><div className="gm-chat-composer-footer"><Typography.Text type="secondary">Enter 发送，Shift + Enter 换行</Typography.Text><Space><Typography.Text type="secondary">{value.length}/12000</Typography.Text><Button type="primary" icon={<SendOutlined />} loading={loading} disabled={!value.trim()} onClick={send}>发送</Button></Space></div></div>;
}

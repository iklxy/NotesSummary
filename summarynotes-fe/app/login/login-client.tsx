"use client";

import { useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { LockOutlined, LoginOutlined, UserOutlined } from "@ant-design/icons";
import { Button, Card, Form, Input, Layout, Typography, message } from "antd";
import { login } from "../../lib/authApi";

const { Content } = Layout;
const { Title, Text, Paragraph } = Typography;

interface LoginFormValues {
  username: string;
  password: string;
}

/**
 * 将 next 参数标准化为站内路径，避免跳转到外部地址。
 *
 * 参数:
 *   value: 查询参数中读取到的 next 值。
 *
 * 返回:
 *   安全的站内跳转路径；非法值统一回退到根路径。
 */
function normalizeRedirectPath(value: string | null): string {
  if (!value) {
    return "/";
  }
  if (!value.startsWith("/")) {
    return "/";
  }
  return value;
}

export default function LoginClient() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [form] = Form.useForm<LoginFormValues>();
  const [submitting, setSubmitting] = useState(false);

  const redirectPath = useMemo(() => {
    return normalizeRedirectPath(searchParams.get("next"));
  }, [searchParams]);

  const handleSubmit = async (values: LoginFormValues) => {
    const username = values.username.trim();
    const password = values.password;
    if (!username || !password) {
      message.warning("请输入用户名和密码");
      return;
    }

    try {
      setSubmitting(true);
      const result = await login({ username, password });
      if (!result.success) {
        message.error(result.message || "登录失败");
        return;
      }
      message.success("登录成功");
      router.replace(redirectPath);
    } catch (e) {
      message.error(e instanceof Error ? e.message : "登录失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Layout
      className="min-h-screen"
      style={{
        background:
          "radial-gradient(circle at top, rgba(56,189,248,0.18), transparent 30%), linear-gradient(180deg, #f8fafc 0%, #eef4fb 100%)",
      }}
    >
      <Content className="flex items-center justify-center p-6">
        <Card
          style={{
            width: "100%",
            maxWidth: 420,
            borderRadius: 24,
            border: "1px solid rgba(148,163,184,0.24)",
            boxShadow: "0 28px 60px -34px rgba(15, 23, 42, 0.38)",
          }}
          bodyStyle={{ padding: 28 }}
        >
          <div style={{ marginBottom: 24 }}>
            <Text
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 8,
                fontSize: 12,
                letterSpacing: "0.14em",
                color: "#0ea5e9",
                fontWeight: 700,
              }}
            >
              SUMMARYNOTES
            </Text>
            <Title level={2} style={{ marginTop: 8, marginBottom: 8 }}>
              内部访谈工作台
            </Title>
            <Paragraph type="secondary" style={{ marginBottom: 0 }}>
              请输入账号密码后进入项目与访谈管理页面。
            </Paragraph>
          </div>

          <Form
            form={form}
            layout="vertical"
            requiredMark={false}
            onFinish={(values) => void handleSubmit(values)}
            autoComplete="off"
          >
            <Form.Item
              label="用户名"
              name="username"
              rules={[{ required: true, message: "请输入用户名" }]}
            >
              <Input
                size="large"
                prefix={<UserOutlined />}
                placeholder="请输入用户名"
                autoComplete="username"
              />
            </Form.Item>

            <Form.Item
              label="密码"
              name="password"
              rules={[{ required: true, message: "请输入密码" }]}
            >
              <Input.Password
                size="large"
                prefix={<LockOutlined />}
                placeholder="请输入密码"
                autoComplete="current-password"
              />
            </Form.Item>

            <Form.Item style={{ marginBottom: 0 }}>
              <Button
                type="primary"
                htmlType="submit"
                size="large"
                block
                loading={submitting}
                icon={<LoginOutlined />}
              >
                登录
              </Button>
            </Form.Item>
          </Form>
        </Card>
      </Content>
    </Layout>
  );
}

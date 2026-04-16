"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Card, Col, Form, Input, Layout, List, Modal, Row, Select, Space, Typography, message } from "antd";
import { DatePicker, Upload } from "antd";
import type { UploadFile } from "antd/es/upload/interface";
import { DownOutlined, MinusCircleOutlined, PlusOutlined } from "@ant-design/icons";
import { Project } from "../lib/types";
import { createProject, getProjects } from "../lib/projectsApi";
import {
  deleteInterview,
  createInterview,
  getProjectInterviews,
  getQuestionIntents,
} from "../lib/interviewsApi";
import type { QuestionIntentItem } from "../lib/types";

const { Header, Content } = Layout;
const { Title, Text, Paragraph } = Typography;

export default function Home() {
  const router = useRouter();
  const [projects, setProjects] = useState<Project[]>([]);
  const [modalVisible, setModalVisible] = useState(false);
  const [editingProject, setEditingProject] = useState<Project | null>(null);
  const [interviewModalVisible, setInterviewModalVisible] = useState(false);
  const [currentProjectForInterview, setCurrentProjectForInterview] = useState<Project | null>(
    null,
  );
  const [questionIntents, setQuestionIntents] = useState<QuestionIntentItem[]>([]);
  const [questionIntentsLoading, setQuestionIntentsLoading] = useState(false);
  const [form] = Form.useForm();
  const [interviewForm] = Form.useForm();
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [expandedProjectIds, setExpandedProjectIds] = useState<number[]>([]);

  const openCreateProject = () => {
    setEditingProject(null);
    form.resetFields();
    setModalVisible(true);
  };

  useEffect(() => {
    const loadProjects = async () => {
      try {
        const data = await getProjects();
        setProjects(data);
      } catch (e) {
        if (e instanceof Error) {
          message.error(e.message);
        } else {
          message.error("加载项目列表失败");
        }
      }
    };
    loadProjects();
  }, []);

  useEffect(() => {
    const loadQuestionIntents = async () => {
      try {
        setQuestionIntentsLoading(true);
        const data = await getQuestionIntents();
        setQuestionIntents(data);
      } catch (e) {
        if (e instanceof Error) {
          message.error(e.message);
        } else {
          message.error("加载问题类型失败");
        }
      } finally {
        setQuestionIntentsLoading(false);
      }
    };

    void loadQuestionIntents();
  }, []);

  const openEditProject = (project: Project) => {
    setEditingProject(project);
    form.setFieldsValue({
      name: project.name,
      keywords: project.keywords ?? "",
      core_description: project.core_problem ?? "",
    });
    setModalVisible(true);
  };

  const handleProjectOk = async () => {
    try {
      const values = await form.validateFields();
      if (editingProject) {
        setProjects((prev) =>
          prev.map((p) =>
            p.id === editingProject.id
              ? {
                ...p,
                name: values.name as string,
                keywords: (values.keywords as string) || null,
                core_problem: (values.core_description as string) || null,
              }
              : p,
          ),
        );
        message.success("项目已更新");
      } else {
        const payload = {
          name: values.name as string,
          keywords: (values.keywords as string) || undefined,
          core_problem: (values.core_description as string) || undefined,
        };
        const created = await createProject(payload);
        setProjects((prev) => [...prev, created]);
        message.success("项目已创建");
      }
      setModalVisible(false);
    } catch (e) {
      if (e instanceof Error) {
        message.error(e.message);
      } else {
        message.warning("请检查表单填写");
      }
    }
  };

  const handleProjectCancel = () => {
    setModalVisible(false);
  };

  const openCreateInterview = (project: Project) => {
    if (questionIntentsLoading) {
      message.info("正在加载问题类型，请稍候");
      return;
    }
    if (questionIntents.length === 0) {
      message.error("问题类型为空，无法新建访谈");
      return;
    }
    setCurrentProjectForInterview(project);
    interviewForm.resetFields();
    interviewForm.setFieldsValue({
      questions: [
        {
          question_text: "",
          question_type: "OPEN",
          intent_id: questionIntents[0]?.id,
        },
      ],
    });
    setFileList([]);
    setInterviewModalVisible(true);
  };

  const handleInterviewCancel = () => {
    setInterviewModalVisible(false);
  };

  const handleInterviewOk = async () => {
    try {
      await interviewForm.validateFields();
      if (!currentProjectForInterview) {
        message.error("缺少项目信息");
        return;
      }
      const values = interviewForm.getFieldsValue();
      const dateValue = values.interview_date;
      let dateText: string | null = null;
      if (dateValue && typeof (dateValue as { format?: unknown }).format === "function") {
        dateText = (dateValue as { format: (fmt: string) => string }).format("YYYY-MM-DD");
      }
      const questions = Array.isArray(values.questions) ? values.questions : [];
      const normalizedQuestions = questions.map(
        (item: { question_text?: string; question_type?: string; intent_id?: number } | undefined) => ({
          question_text: (item?.question_text ?? "").trim(),
          question_type: (item?.question_type ?? "OPEN").trim().toUpperCase(),
          intent_id: item?.intent_id,
        }),
      ) as Array<{ question_text: string; question_type: string; intent_id?: number }>;

      if (normalizedQuestions.length === 0) {
        message.error("请至少填写一个需总结的问题");
        return;
      }

      const missingQuestion = normalizedQuestions.some(
        (item: { question_text: string }) => !item.question_text,
      );
      if (missingQuestion) {
        message.error("请先补全所有需总结的问题");
        return;
      }

      const missingIntent = normalizedQuestions.some(
        (item: { intent_id?: number }) => !item.intent_id,
      );
      if (missingIntent) {
        message.error("请先为每个问题选择 intent");
        return;
      }

      const formData = new FormData();
      formData.append("name", values.interview_name as string);
      if (dateText) {
        formData.append("interview_date", dateText);
      }
      formData.append("questions_json", JSON.stringify(normalizedQuestions));
      const file = fileList[0];
      if (!file || !file.originFileObj) {
        message.error("请先选择音频文件");
        return;
      }
      formData.append("file", file.originFileObj as File);

      const created = await createInterview(currentProjectForInterview.id, formData);

      setProjects((prev) =>
        prev.map((p) => {
          if (p.id !== currentProjectForInterview.id) {
            return p;
          }
          const currentInterviews = p.interviews ?? [];
          const next = {
            id: created.id,
            name: created.name,
            date: created.interview_date ?? dateText,
            audioFileName: created.file_name,
          };
          return { ...p, interviews: [...currentInterviews, next] };
        }),
      );
      setExpandedProjectIds((prev) =>
        prev.includes(currentProjectForInterview.id)
          ? prev
          : [...prev, currentProjectForInterview.id],
      );
      message.success("访谈信息已填写");
      setInterviewModalVisible(false);
      router.push(`/interviews/${created.id}/processing`);
    } catch (e) {
      if (e instanceof Error) {
        message.error(e.message);
      } else {
        message.warning("请完善访谈信息");
      }
    }
  };

  const toggleProjectExpanded = async (project: Project) => {
    if (expandedProjectIds.includes(project.id)) {
      setExpandedProjectIds((prev) => prev.filter((id) => id !== project.id));
      return;
    }
    if (!project.interviews) {
      try {
        const list = await getProjectInterviews(project.id);
        const mapped = list.map((item) => ({
          id: item.id,
          name: item.name,
          date: item.interview_date ?? null,
          audioFileName: item.file_name ?? null,
        }));
        setProjects((prev) =>
          prev.map((p) => (p.id === project.id ? { ...p, interviews: mapped } : p)),
        );
      } catch (e) {
        if (e instanceof Error) {
          message.error(e.message);
        } else {
          message.error("加载访谈列表失败");
        }
      }
    }
    setExpandedProjectIds((prev) =>
      prev.includes(project.id) ? prev : [...prev, project.id],
    );
  };

  const handleDeleteInterview = (projectId: number, interviewId: number, interviewName: string) => {
    Modal.confirm({
      title: "确认删除访谈",
      content: `确定要删除访谈「${interviewName}」吗？该操作会同时删除数据库中的访谈、题目和原文数据。`,
      okText: "删除",
      okType: "danger",
      cancelText: "取消",
      onOk: async () => {
        try {
          await deleteInterview(interviewId);
          setProjects((prev) =>
            prev.map((p) =>
              p.id === projectId
                ? {
                    ...p,
                    interviews: (p.interviews ?? []).filter((it) => it.id !== interviewId),
                  }
                : p,
            ),
          );
          message.success("访谈已删除");
        } catch (e) {
          if (e instanceof Error) {
            message.error(e.message);
          } else {
            message.error("删除访谈失败");
          }
        }
      },
    });
  };

  return (
    <Layout className="min-h-screen">
      <Header className="flex items-center justify-between bg-slate-900 shadow px-6">
        <Title level={3} className="mb-0" style={{ color: "#ffffff" }}>
          SummaryNotes 项目列表
        </Title>
      </Header>
      <Content className="p-6 bg-slate-50">
        <Row gutter={[16, 16]}>
          <Col span={24}>
            <Card>
              <div className="flex items-center justify-between mb-4">
                <Title level={4} style={{ marginBottom: 0 }}>
                  项目列表
                </Title>
                <Button type="primary" onClick={openCreateProject}>
                  新建项目
                </Button>
              </div>
              {projects.length === 0 ? (
                <Text type="secondary">当前暂无项目，请点击右侧“新建项目”。</Text>
              ) : (
                <List
                  itemLayout="vertical"
                  dataSource={projects}
                  renderItem={(project) => (
                    <List.Item>
                      <Card>
                        <Space direction="vertical" size="small" style={{ width: "100%" }}>
                          <Space className="justify-between w-full">
                            <Space>
                              <Button
                                type="text"
                                size="small"
                                icon={
                                  <DownOutlined
                                    rotate={expandedProjectIds.includes(project.id) ? 180 : 0}
                                  />
                                }
                                onClick={() => {
                                  void toggleProjectExpanded(project);
                                }}
                              />
                              <Title level={5} style={{ marginBottom: 0 }}>
                                {project.name}
                              </Title>
                            </Space>
                            <Space>
                              <Button
                                type="primary"
                                ghost
                                onClick={() => openCreateInterview(project)}
                              >
                                新建访谈
                              </Button>
                              <Button type="default" onClick={() => openEditProject(project)}>
                                编辑项目
                              </Button>
                            </Space>
                          </Space>
                          {project.keywords && (
                            <Text type="secondary">关键词：{project.keywords}</Text>
                          )}
                          {project.core_problem && (
                            <Paragraph style={{ marginBottom: 0 }}>
                              核心描述：{project.core_problem}
                            </Paragraph>
                          )}
                          {expandedProjectIds.includes(project.id) && (
                            <div style={{ marginTop: 8 }}>
                              <Text strong>访谈列表</Text>
                              {project.interviews && project.interviews.length > 0 ? (
                                <List
                                  size="small"
                                  dataSource={project.interviews}
                                  renderItem={(interview) => (
                                    <List.Item
                                      actions={[
                                        <Button
                                          key="detail"
                                          type="link"
                                          size="small"
                                          onClick={() => router.push(`/interviews/${interview.id}`)}
                                        >
                                          详情
                                        </Button>,
                                          <Button
                                            key="delete"
                                            type="link"
                                            size="small"
                                            danger
                                            onClick={() =>
                                              handleDeleteInterview(
                                                project.id,
                                                interview.id,
                                                interview.name,
                                              )
                                            }
                                          >
                                            删除
                                          </Button>,
                                      ]}
                                    >
                                      <Space direction="vertical" size={0}>
                                        <Text>{interview.name}</Text>
                                        <Text type="secondary" style={{ fontSize: 12 }}>
                                          {interview.date ? `访谈时间：${interview.date}` : ""}
                                          {interview.audioFileName
                                            ? `${interview.date ? "，" : ""}文件：${interview.audioFileName
                                            }`
                                            : ""}
                                        </Text>
                                      </Space>
                                    </List.Item>
                                  )}
                                />
                              ) : (
                                <Text type="secondary" style={{ fontSize: 12 }}>
                                  暂无访谈。
                                </Text>
                              )}
                            </div>
                          )}
                        </Space>
                      </Card>
                    </List.Item>
                  )}
                />
              )}
            </Card>
          </Col>
        </Row>
      </Content>
      <Modal
        open={modalVisible}
        title={editingProject ? "编辑项目" : "新建项目"}
        onOk={handleProjectOk}
        onCancel={handleProjectCancel}
        okText="确认"
        cancelText="取消"
        destroyOnHidden
      >
        <Form form={form} layout="vertical">
          <Form.Item
            label="项目名称"
            name="name"
            rules={[{ required: true, message: "请输入项目名称" }]}
          >
            <Input placeholder="请输入项目名称" />
          </Form.Item>
          <Form.Item label="项目关键词" name="keywords">
            <Input placeholder="可选，多个关键词用逗号分隔" />
          </Form.Item>
          <Form.Item label="访谈核心描述" name="core_description">
            <Input.TextArea
              rows={3}
              placeholder="可选，用一句话描述这个项目的访谈在做什么"
            />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        open={interviewModalVisible}
        title="新建访谈"
        onOk={handleInterviewOk}
        onCancel={handleInterviewCancel}
        okText="确定"
        cancelText="取消"
        destroyOnHidden
      >
        {currentProjectForInterview ? (
          <Form form={interviewForm} layout="vertical">
            <Form.Item label="所属项目">
              <Text>{currentProjectForInterview.name}</Text>
            </Form.Item>
            <Form.Item
              label="访谈名称"
              name="interview_name"
              rules={[{ required: true, message: "请输入访谈名称" }]}
            >
              <Input placeholder="请输入访谈名称" />
            </Form.Item>
            <Form.Item label="访谈时间" name="interview_date">
              <DatePicker style={{ width: "100%" }} placeholder="请选择访谈时间" />
            </Form.Item>
            <Form.Item label="录音文件上传">
              <div>
                <Upload
                  beforeUpload={() => false}
                  maxCount={1}
                  fileList={fileList}
                  onChange={({ fileList: newList }) => setFileList(newList)}
                  accept=".wav,.mp3,.m4a"
                >
                  <Button>选择文件</Button>
                </Upload>
                <Text type="secondary" style={{ fontSize: 12, marginTop: 8, display: "block" }}>
                  支持上传wav、mp3、m4a格式音频文件，单次仅支持上传一个文件，文件大小不超过1G。
                </Text>
              </div>
            </Form.Item>
            <Form.List name="questions">
              {(fields, { add, remove }) => (
                <div style={{ marginBottom: 16 }}>
                  <Space className="justify-between w-full" style={{ marginBottom: 8 }}>
                    <Text strong>需总结的问题</Text>
                    <Button
                      type="dashed"
                      icon={<PlusOutlined />}
                      onClick={() =>
                        add({
                          question_text: "",
                          question_type: "OPEN",
                          intent_id: questionIntents[0]?.id,
                        })
                      }
                    >
                      添加问题
                    </Button>
                  </Space>
                  <Space direction="vertical" style={{ width: "100%" }} size="middle">
                    {fields.map((field, index) => (
                      <Card
                        key={field.key}
                        size="small"
                        styles={{ body: { padding: 12 } }}
                      >
                        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                          <Form.Item
                            label={index === 0 ? "问题内容" : undefined}
                            name={[field.name, "question_text"]}
                            rules={[{ required: true, message: "请输入需总结的问题" }]}
                            style={{ marginBottom: 0 }}
                          >
                            <Input.TextArea rows={2} placeholder="请输入需总结的问题" />
                          </Form.Item>
                          <div
                            style={{
                              display: "flex",
                              gap: 12,
                              alignItems: "flex-start",
                            }}
                          >
                            <Form.Item
                              label={index === 0 ? "问题类型" : undefined}
                              name={[field.name, "question_type"]}
                              rules={[{ required: true, message: "请选择问题类型" }]}
                              initialValue="OPEN"
                              style={{ flex: 0.8, marginBottom: 0 }}
                            >
                              <Select
                                options={[
                                  { label: "OPEN", value: "OPEN" },
                                  { label: "SUMMARY", value: "SUMMARY" },
                                  { label: "QUERY", value: "QUERY" },
                                ]}
                              />
                            </Form.Item>
                            <Form.Item
                              label={index === 0 ? "Intent" : undefined}
                              name={[field.name, "intent_id"]}
                              rules={[{ required: true, message: "请选择 intent" }]}
                              style={{ flex: 1.2, marginBottom: 0 }}
                            >
                              <Select
                                placeholder="请选择 intent"
                                options={questionIntents.map((intent) => ({
                                  label: `${intent.id} - ${intent.code}`,
                                  value: intent.id,
                                }))}
                              />
                            </Form.Item>
                            <Button
                              danger
                              type="text"
                              icon={<MinusCircleOutlined />}
                              disabled={fields.length === 1}
                              onClick={() => remove(field.name)}
                              style={{ marginTop: index === 0 ? 28 : 0 }}
                            />
                          </div>
                        </div>
                      </Card>
                    ))}
                  </Space>
                </div>
              )}
            </Form.List>
          </Form>
        ) : (
          <Paragraph>请选择一个项目后再新建访谈。</Paragraph>
        )}
      </Modal>
    </Layout>
  );
}

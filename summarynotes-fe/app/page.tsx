"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Card, Col, Form, Input, Layout, List, Modal, Row, Space, Typography, message } from "antd";
import { DatePicker, Upload } from "antd";
import type { UploadFile } from "antd/es/upload/interface";
import { DownOutlined } from "@ant-design/icons";
import { Project } from "../lib/types";
import { createProject, getProjects } from "../lib/projectsApi";
import {
  deleteInterview,
  createInterview,
  getProjectInterviews,
} from "../lib/interviewsApi";
import HotwordSelector from "../components/HotwordSelector";
import { INTERVIEW_HOTWORD_OPTIONS } from "../lib/hotwordOptions";

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
  const [form] = Form.useForm();
  const [interviewForm] = Form.useForm();
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [expandedProjectIds, setExpandedProjectIds] = useState<number[]>([]);
  const [selectedInterviewHotwordValues, setSelectedInterviewHotwordValues] = useState<string[]>(
    [],
  );

  const formatInterviewDate = (value?: string | null) => {
    if (!value) {
      return "";
    }
    return value.includes("T") ? value.split("T")[0] : value;
  };

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

  const openEditProject = (project: Project) => {
    setEditingProject(project);
    form.setFieldsValue({
      name: project.name,
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
                  core_problem: (values.core_description as string) || null,
                }
              : p,
          ),
        );
        message.success("项目已更新");
      } else {
        const payload = {
          name: values.name as string,
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
    setCurrentProjectForInterview(project);
    interviewForm.resetFields();
    setFileList([]);
    setSelectedInterviewHotwordValues([]);
    setInterviewModalVisible(true);
  };

  const handleInterviewCancel = () => {
    setInterviewModalVisible(false);
    setSelectedInterviewHotwordValues([]);
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
      const formData = new FormData();
      formData.append("name", values.interview_name as string);
      if (dateText) {
        formData.append("interview_date", dateText);
      }
      const file = fileList[0];
      if (!file || !file.originFileObj) {
        message.error("请先选择音频文件");
        return;
      }
      formData.append("file", file.originFileObj as File);
      formData.append("hotword_keys", selectedInterviewHotwordValues.join(","));

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
      setSelectedInterviewHotwordValues([]);
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
      content: `确定要删除访谈「${interviewName}」吗？该操作会同时删除数据库中的访谈、题目、原文、Notes，以及本地和云端音频文件与向量索引。`,
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
      <Content className="bg-slate-50">
        <div className="relative overflow-hidden border-b border-slate-200 bg-gradient-to-r from-slate-950 via-slate-900 to-slate-800 px-6 py-8 shadow-[0_20px_60px_-24px_rgba(15,23,42,0.55)] md:px-10 md:py-10">
          <div className="pointer-events-none absolute -right-10 -top-10 h-40 w-40 rounded-full bg-sky-400/15 blur-3xl" />
          <div className="pointer-events-none absolute -bottom-12 left-1/3 h-44 w-44 rounded-full bg-cyan-300/10 blur-3xl" />
          <div className="relative flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
            <div className="max-w-3xl">
              <div className="inline-flex items-center rounded-full border border-white/10 bg-white/10 px-3 py-1 text-[11px] font-semibold tracking-[0.24em] text-slate-200">
                SUMMARYNOTES
              </div>
              <Title level={2} className="!mb-2 !mt-4 !text-white">
                项目列表
              </Title>
              <Paragraph className="!mb-0 !max-w-2xl !text-slate-300">
                统一管理项目、访谈、题目与 Notes，上传音频后自动进入转录和工作流处理。
              </Paragraph>
            </div>
            <div className="flex items-center gap-4">
              <div className="rounded-2xl border border-white/10 bg-white/10 px-4 py-3 text-right backdrop-blur-sm">
                <div className="text-xs text-slate-300">当前项目</div>
                <div className="mt-1 text-3xl font-semibold text-white">{projects.length}</div>
              </div>
            </div>
          </div>
        </div>
        <div className="p-6 md:p-8">
          <Row gutter={[16, 16]}>
            <Col span={24}>
              <Card className="summarynotes-project-list-shell">
                <div className="flex items-center justify-between mb-4">
                  <Title level={4} style={{ marginBottom: 0 }} className="summarynotes-section-title">
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
                      <List.Item className="summarynotes-project-list-item">
                        <Card className="summarynotes-project-card">
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
                            {project.core_problem && (
                              <Paragraph style={{ marginBottom: 0 }}>
                                核心描述：{project.core_problem}
                              </Paragraph>
                            )}
                            {expandedProjectIds.includes(project.id) && (
                              <div style={{ marginTop: 8 }} className="summarynotes-interview-panel">
                                <Text strong className="summarynotes-subsection-title">
                                  访谈列表
                                </Text>
                                {project.interviews && project.interviews.length > 0 ? (
                                  <List
                                    size="small"
                                    dataSource={project.interviews}
                                    renderItem={(interview) => (
                                      <List.Item
                                        className="summarynotes-interview-item"
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
                                            {interview.date
                                              ? `访谈时间：${formatInterviewDate(interview.date)}`
                                              : ""}
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
                                  <Text type="secondary" style={{ fontSize: 12 }} className="summarynotes-empty-hint">
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
        </div>
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
          <Form.Item label="访谈核心描述" name="core_description">
            <Input.TextArea
              rows={5}
              placeholder={`请填写：
研究目标：这次访谈主要想了解什么？想知道什么？
访谈背景：这次访谈属于哪类业务？例如肺癌相关业务、糖尿病相关业务、患者教育、院内用药流程等。`}
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
            <Form.Item label="访谈级热词">
              <HotwordSelector
                title="访谈热词"
                description="选择本次访谈热词。当前包含原项目级与访谈级词包。"
                options={INTERVIEW_HOTWORD_OPTIONS}
                selectedKeys={selectedInterviewHotwordValues}
                onChange={setSelectedInterviewHotwordValues}
              />
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
          </Form>
        ) : (
          <Paragraph>请选择一个项目后再新建访谈。</Paragraph>
        )}
      </Modal>
    </Layout>
  );
}

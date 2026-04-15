"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Card, Col, Form, Input, Layout, List, Modal, Row, Space, Typography, message } from "antd";
import { DatePicker, Upload } from "antd";
import type { UploadFile } from "antd/es/upload/interface";
import { DownOutlined } from "@ant-design/icons";
import { Project } from "../lib/types";
import { createProject, getProjects } from "../lib/projectsApi";
import { createInterview, getProjectInterviews } from "../lib/interviewsApi";

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
    setCurrentProjectForInterview(project);
    interviewForm.resetFields();
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

  const handleDeleteInterview = (projectId: number, interviewId: number) => {
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
                                            handleDeleteInterview(project.id, interview.id)
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
            <Form.Item label="录音文件上传" name="audio_file">
              <>
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
              </>
            </Form.Item>
          </Form>
        ) : (
          <Paragraph>请选择一个项目后再新建访谈。</Paragraph>
        )}
      </Modal>
    </Layout>
  );
}

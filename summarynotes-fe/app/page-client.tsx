"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Button,
  Card,
  Col,
  Form,
  Input,
  Layout,
  List,
  Modal,
  Row,
  Space,
  Tag,
  Typography,
  Upload,
  message,
} from "antd";
import type { UploadFile } from "antd/es/upload/interface";
import { UploadOutlined } from "@ant-design/icons";
import { Project } from "../lib/types";
import { createProject, deleteProject, getProjects, updateProject } from "../lib/projectsApi";

const { Content } = Layout;
const { Title, Text, Paragraph } = Typography;

export default function Home() {
  const router = useRouter();
  const [projects, setProjects] = useState<Project[]>([]);
  const [modalVisible, setModalVisible] = useState(false);
  const [editingProject, setEditingProject] = useState<Project | null>(null);
  const [guideFileList, setGuideFileList] = useState<UploadFile[]>([]);
  const [form] = Form.useForm();

  useEffect(() => {
    const loadProjects = async () => {
      try {
        const data = await getProjects();
        setProjects(data);
      } catch (e) {
        message.error(e instanceof Error ? e.message : "加载项目列表失败");
      }
    };
    void loadProjects();
  }, []);

  const openCreateProject = () => {
    setEditingProject(null);
    form.resetFields();
    setGuideFileList([]);
    setModalVisible(true);
  };

  const openEditProject = (project: Project) => {
    setEditingProject(project);
    form.setFieldsValue({
      name: project.name,
      core_description: project.core_problem ?? "",
    });
    setGuideFileList([]);
    setModalVisible(true);
  };

  const handleProjectOk = async () => {
    try {
      const values = await form.validateFields();
      if (editingProject) {
        const updated = await updateProject(editingProject.id, {
          name: values.name as string,
          core_problem: String(values.core_description ?? ""),
        });
        setProjects((prev) =>
          prev.map((item) =>
            item.id === editingProject.id
              ? {
                  ...item,
                  ...updated,
                }
              : item,
          ),
        );
        message.success("项目已更新");
      } else {
        const created = await createProject({
          name: values.name as string,
          core_problem: (values.core_description as string) || undefined,
          guide_file: guideFileList[0]?.originFileObj as File | null | undefined,
        });
        setProjects((prev) => [created, ...prev]);
        message.success(
          guideFileList.length > 0
            ? "项目已创建，指南正在异步学习中，请稍后在项目详情查看结果"
            : "项目已创建",
        );
      }
      setModalVisible(false);
    } catch (e) {
      message.error(e instanceof Error ? e.message : "请检查表单填写");
    }
  };

  const handleDeleteProject = (project: Project) => {
    Modal.confirm({
      title: "确认删除项目",
      content: `确定要删除项目「${project.name}」吗？该操作会同时删除该项目下的所有访谈、问题、summary、Notes、few-shot 样本，以及本地/云端音频和向量索引，且不可恢复。`,
      okText: "删除",
      okType: "danger",
      cancelText: "取消",
      onOk: async () => {
        try {
          const resp = await deleteProject(project.id);
          if (resp.warnings && resp.warnings.length > 0) {
            message.warning(`项目已删除，但部分外部资源清理失败：${resp.warnings.join("；")}`);
          } else {
            message.success("项目已删除");
          }
          setProjects((prev) => prev.filter((item) => item.id !== project.id));
        } catch (e) {
          message.error(e instanceof Error ? e.message : "删除项目失败");
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
                点击任意项目进入项目详情页，在详情页中管理 DG、项目 Key BQ、访谈创建和 CA。
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
                <div className="mb-4 flex items-center justify-between">
                  <Title level={4} style={{ marginBottom: 0 }} className="summarynotes-section-title">
                    项目入口
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
                        <Card
                          className="summarynotes-project-card"
                          role="button"
                          tabIndex={0}
                          onClick={() => router.push(`/projects/${project.id}`)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter" || event.key === " ") {
                              event.preventDefault();
                              router.push(`/projects/${project.id}`);
                            }
                          }}
                          style={{ cursor: "pointer" }}
                        >
                          <Space direction="vertical" size="small" style={{ width: "100%" }}>
                            <Space className="justify-between w-full" align="start">
                              <Space direction="vertical" size={4}>
                                <Title level={5} style={{ marginBottom: 0 }}>
                                  {project.name}
                                </Title>
                                {project.guide_status ? (
                                  <Text type="secondary" style={{ fontSize: 12 }}>
                                    指南状态：{project.guide_status}
                                  </Text>
                                ) : null}
                              </Space>
                              <Space>
                                <Button
                                  type="default"
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    openEditProject(project);
                                  }}
                                >
                                  编辑项目
                                </Button>
                                <Button
                                  danger
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    handleDeleteProject(project);
                                  }}
                                >
                                  删除项目
                                </Button>
                              </Space>
                            </Space>

                            <Space wrap size={6}>
                              <Tag color="cyan">问卷 {project.questionnaire_count ?? 0}</Tag>
                              <Tag color="geekblue">Key BQ {project.key_bq_count ?? 0}</Tag>
                              <Tag color="green">访谈 {project.interview_count ?? 0}</Tag>
                            </Space>
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
        onOk={() => void handleProjectOk()}
        onCancel={() => {
          setModalVisible(false);
          setGuideFileList([]);
        }}
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
          {!editingProject ? (
            <Form.Item label="上传指南">
              <Upload
                beforeUpload={() => false}
                maxCount={1}
                fileList={guideFileList}
                onChange={({ fileList }) => setGuideFileList(fileList)}
                accept=".pdf"
              >
                <Button icon={<UploadOutlined />}>选择 PDF 指南</Button>
              </Upload>
              <Typography.Text type="secondary" style={{ fontSize: 12, marginTop: 8, display: "block" }}>
                指南为可选附件，上传后会异步做全文学习总结，并可在项目详情页查看结果。
              </Typography.Text>
            </Form.Item>
          ) : null}
        </Form>
      </Modal>
    </Layout>
  );
}

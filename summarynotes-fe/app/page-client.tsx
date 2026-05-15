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
import BrandHero from "../components/BrandHero";
import { Project } from "../lib/types";
import { createProject, deleteProject, getProjects } from "../lib/projectsApi";

const { Content } = Layout;
const { Title, Text } = Typography;

export default function Home() {
  const router = useRouter();
  const [projects, setProjects] = useState<Project[]>([]);
  const [modalVisible, setModalVisible] = useState(false);
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
    form.resetFields();
    setGuideFileList([]);
    setModalVisible(true);
  };

  const openProjectDetail = (project: Project) => {
    router.push(`/projects/${project.id}`);
  };

  const handleProjectOk = async () => {
    try {
      const values = await form.validateFields();
      const created = await createProject({
        name: values.name as string,
        guide_files: guideFileList
          .map((item) => item.originFileObj as File | null | undefined)
          .filter((file): file is File => Boolean(file)),
      });
      setProjects((prev) => [created, ...prev]);
      message.success(
        guideFileList.length > 0
          ? "项目已创建，指南正在异步学习中，请稍后在项目详情查看结果"
          : "项目已创建",
      );
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
      <BrandHero
        className="mt-4 mb-18 lg:mt-6 lg:mb-24"
        title="项目列表"
        description="点击任意项目进入项目详情页，在详情页中管理 DG、项目 Key BQ、访谈创建和 CA。"
        titleClassName="text-[42px] leading-tight md:text-[52px]"
        descriptionClassName="text-[18px] md:text-[20px]"
        stats={
          <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-right shadow-[0_12px_28px_-20px_rgba(15,23,42,0.22)]">
            <div className="text-xs text-slate-500">当前项目</div>
            <div className="mt-1 text-3xl font-semibold text-slate-900">{projects.length}</div>
          </div>
        }
      />
      <Content className="bg-slate-50 pt-10 lg:pt-2">
        <div className="p-6 md:p-8">
          <Row gutter={[16, 16]}>
            <Col span={24}>
              <div className="summarynotes-page-intro-block">
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
                                    openProjectDetail(project);
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
              </div>
            </Col>
          </Row>
        </div>
      </Content>

      <Modal
        open={modalVisible}
        title="新建项目"
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
          <Form.Item label="上传指南">
            <Upload
              beforeUpload={() => false}
              multiple
              fileList={guideFileList}
              onChange={({ fileList }) => setGuideFileList(fileList)}
              accept=".pdf,.docx,.md,.xlsx"
            >
              <Button icon={<UploadOutlined />}>选择指南文件</Button>
            </Upload>
            <Typography.Text type="secondary" style={{ fontSize: 12, marginTop: 8, display: "block" }}>
              支持一次上传多个 pdf、docx、md 或 xlsx 文件，上传后会异步做汇总学习，并自动生成项目背景说明。
            </Typography.Text>
          </Form.Item>
        </Form>
      </Modal>
    </Layout>
  );
}

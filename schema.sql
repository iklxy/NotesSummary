/*M!999999\- enable the sandbox mode */ 
-- MariaDB dump 10.19  Distrib 10.11.15-MariaDB, for Linux (aarch64)
--
-- Host: 124.221.27.111    Database: summarynotes
-- ------------------------------------------------------
-- Server version	8.0.46

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `bh_project`
--

DROP TABLE IF EXISTS `bh_project`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `bh_project` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `keywords` text COLLATE utf8mb4_unicode_ci,
  `core_problem` text COLLATE utf8mb4_unicode_ci,
  `guide_file_name` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '项目指南原始文件名',
  `guide_file_path` text COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '项目指南文件路径',
  `key_bq_json` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL COMMENT '项目级共享 Key BQ JSON',
  `created_by_user_id` bigint unsigned NOT NULL COMMENT '创建该项目的用户ID',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_bh_project_name` (`name`),
  KEY `idx_bh_project_created_by_user_id` (`created_by_user_id`),
  CONSTRAINT `bh_project_chk_key_bq_json` CHECK (`key_bq_json` IS NULL OR json_valid(`key_bq_json`))
) ENGINE=InnoDB AUTO_INCREMENT=6 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `bh_project_guide`
--

DROP TABLE IF EXISTS `bh_project_guide`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `bh_project_guide` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `project_id` bigint NOT NULL COMMENT '关联 bh_project.id',
  `guide_file_name` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '项目指南原始文件名',
  `guide_file_path` text COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '项目指南文件路径',
  `file_type` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'pdf' COMMENT '文件类型：pdf 等',
  `extracted_text` longtext COLLATE utf8mb4_unicode_ci COMMENT 'PDF 抽取 / OCR 后的全文文本',
  `summary_text` longtext COLLATE utf8mb4_unicode_ci COMMENT '模型生成的项目指南学习总结',
  `status` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'queued' COMMENT 'queued/extracting/summarizing/done/failed',
  `error_message` text COLLATE utf8mb4_unicode_ci COMMENT '失败原因',
  `generated_at` datetime DEFAULT NULL COMMENT '最近一次成功生成时间',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_bh_project_guide_project_id` (`project_id`),
  KEY `idx_bh_project_guide_status` (`status`),
  CONSTRAINT `fk_bh_project_guide_project`
    FOREIGN KEY (`project_id`) REFERENCES `bh_project` (`id`)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `bh_project_guide_chk_1`
    CHECK (`file_type` <> '' AND `status` <> '')
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `bh_project_ca_table`
--

DROP TABLE IF EXISTS `bh_project_ca_table`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `bh_project_ca_table` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `project_id` bigint unsigned NOT NULL COMMENT '项目ID',
  `ca_json` longtext COMMENT 'CA表结构化JSON',
  `status` varchar(32) NOT NULL DEFAULT 'done' COMMENT '状态：done/failed/pending',
  `error_message` text COMMENT '错误信息',
  `generated_at` datetime DEFAULT NULL COMMENT '最近一次成功生成时间',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_bh_project_ca_table_project_id` (`project_id`),
  KEY `idx_bh_project_ca_table_status` (`status`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='项目CA表';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `bh_project_fewshot_sample`
--

DROP TABLE IF EXISTS `bh_project_fewshot_sample`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `bh_project_fewshot_sample` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `project_id` bigint NOT NULL,
  `project_interview_id` bigint DEFAULT NULL,
  `question_id` bigint NOT NULL,
  `intent_id` bigint NOT NULL,
  `notes_result_id` bigint DEFAULT NULL,
  `sample_json` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `quality_score` tinyint NOT NULL,
  `source_kind` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_bh_fewshot_project` (`project_id`),
  KEY `idx_bh_fewshot_interview` (`project_interview_id`),
  KEY `idx_bh_fewshot_question` (`question_id`),
  KEY `idx_bh_fewshot_intent` (`intent_id`),
  KEY `idx_bh_fewshot_notes` (`notes_result_id`),
  KEY `idx_bh_fewshot_quality` (`quality_score`),
  CONSTRAINT `bh_project_fewshot_sample_chk_1` CHECK (json_valid(`sample_json`))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `bh_project_interview`
--

DROP TABLE IF EXISTS `bh_project_interview`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `bh_project_interview` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `parse_project_id` bigint NOT NULL,
  `name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `keywords` text COLLATE utf8mb4_unicode_ci,
  `core_problem` text COLLATE utf8mb4_unicode_ci,
  `questionnaire_id` bigint DEFAULT NULL COMMENT '关联 bh_project_questionnaire.id',
  `key_bq_id` bigint DEFAULT NULL COMMENT '关联 bh_project_key_bq.id',
  `interview_date` datetime DEFAULT NULL,
  `hospital_city` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '医院所在城市',
  `hospital_decile` tinyint unsigned DEFAULT NULL COMMENT '医院Decile',
  `doctor_level` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '医生级别',
  `file_id` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `file_path` text COLLATE utf8mb4_unicode_ci,
  `file_name` text COLLATE utf8mb4_unicode_ci,
  `file_content` longtext COLLATE utf8mb4_unicode_ci,
  `note_content` longtext COLLATE utf8mb4_unicode_ci,
  `status` tinyint DEFAULT NULL,
  `problem_answer` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin,
  PRIMARY KEY (`id`),
  KEY `idx_bh_project_interview_project_id` (`parse_project_id`),
  KEY `idx_bh_project_interview_questionnaire_id` (`questionnaire_id`),
  KEY `idx_bh_project_interview_key_bq_id` (`key_bq_id`),
  CONSTRAINT `fk_bh_project_interview_project` FOREIGN KEY (`parse_project_id`) REFERENCES `bh_project` (`id`) ON UPDATE CASCADE,
  CONSTRAINT `bh_project_interview_chk_1` CHECK (json_valid(`problem_answer`))
) ENGINE=InnoDB AUTO_INCREMENT=42 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `bh_interview_detail`
--

DROP TABLE IF EXISTS `bh_interview_detail`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `bh_interview_detail` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `interview_id` bigint NOT NULL COMMENT '关联 bh_project_interview.id',
  `detail_json` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL COMMENT '通用访谈细节 JSON',
  `doctor_level` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '医生级别',
  `doctor_title` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '职称',
  `city` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '城市',
  `hospital` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '所在医院',
  `department` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '科室',
  `hospital_decile` tinyint unsigned DEFAULT NULL COMMENT '医院Decile（0-10，0 视为未填写）',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_bh_interview_detail_interview_id` (`interview_id`),
  CONSTRAINT `fk_bh_interview_detail_interview_id`
    FOREIGN KEY (`interview_id`) REFERENCES `bh_project_interview` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `bh_interview_detail_chk_1` CHECK (`detail_json` IS NULL OR json_valid(`detail_json`))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

-- Table structure for table `bh_project_role`
--

DROP TABLE IF EXISTS `bh_project_role`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `bh_project_role` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `project_id` bigint NOT NULL,
  `role_name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '角色名称',
  `role_type` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '角色模板类型：doctor/patient/custom',
  `detail_schema_json` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL COMMENT '访谈细节字段模板 JSON',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_bh_project_role_project_name` (`project_id`,`role_name`),
  KEY `idx_bh_project_role_project_id` (`project_id`),
  CONSTRAINT `fk_bh_project_role_project` FOREIGN KEY (`project_id`) REFERENCES `bh_project` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `bh_project_role_chk_1` CHECK (`detail_schema_json` IS NULL OR json_valid(`detail_schema_json`))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `bh_project_questionnaire`
--

DROP TABLE IF EXISTS `bh_project_questionnaire`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `bh_project_questionnaire` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `project_id` bigint NOT NULL,
  `role_id` bigint DEFAULT NULL COMMENT '关联 bh_project_role.id',
  `object_type` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '访谈对象类型：patient/doctor',
  `name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '问卷名称',
  `file_name` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '上传的原始文件名',
  `docx_path` text COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '原始 docx 文件路径',
  `md_path` text COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '问卷解析后 md 文件路径',
  `json_path` text COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '问卷解析后 json 文件路径',
  `hotwords` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL COMMENT '绑定的热词列表，JSON 数组字符串',
  `status` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'hotword_review_pending' COMMENT 'hotword_review_pending | ready | failed',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_bh_project_questionnaire_role_id` (`role_id`),
  KEY `idx_bh_project_questionnaire_project_id` (`project_id`),
  CONSTRAINT `fk_bh_project_questionnaire_project` FOREIGN KEY (`project_id`) REFERENCES `bh_project` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_bh_project_questionnaire_role` FOREIGN KEY (`role_id`) REFERENCES `bh_project_role` (`id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `bh_project_questionnaire_chk_1` CHECK (`hotwords` IS NULL OR json_valid(`hotwords`))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `bh_project_key_bq`
--

DROP TABLE IF EXISTS `bh_project_key_bq`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `bh_project_key_bq` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `project_id` bigint NOT NULL,
  `name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'Key BQ 组名称',
  `key_bq_json` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL COMMENT 'Key BQ JSON',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_bh_project_key_bq_project_name` (`project_id`,`name`),
  KEY `idx_bh_project_key_bq_project_id` (`project_id`),
  CONSTRAINT `fk_bh_project_key_bq_project` FOREIGN KEY (`project_id`) REFERENCES `bh_project` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `bh_project_key_bq_chk_1` CHECK (json_valid(`key_bq_json`))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

ALTER TABLE `bh_project_interview`
  ADD CONSTRAINT `fk_bh_project_interview_questionnaire`
    FOREIGN KEY (`questionnaire_id`) REFERENCES `bh_project_questionnaire` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  ADD CONSTRAINT `fk_bh_project_interview_key_bq`
    FOREIGN KEY (`key_bq_id`) REFERENCES `bh_project_key_bq` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE;

--
-- Table structure for table `bh_project_interview_key_bq`
--

DROP TABLE IF EXISTS `bh_project_interview_key_bq`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `bh_project_interview_key_bq` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `project_id` bigint unsigned NOT NULL COMMENT '项目ID',
  `project_interview_id` bigint unsigned NOT NULL COMMENT '访谈ID',
  `bq_order` int NOT NULL COMMENT 'key BQ 顺序，从1开始',
  `bq_text` text NOT NULL COMMENT 'key BQ 原文',
  `dimension_json` longtext COMMENT 'KBQ Notes 第一步抽取出的维度JSON',
  `note_json` longtext COMMENT 'KBQ Notes 第二步生成的内容JSON',
  `status` varchar(32) NOT NULL DEFAULT 'pending' COMMENT '状态：pending/done/failed',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_bh_project_interview_key_bq_interview_order` (`project_interview_id`,`bq_order`),
  KEY `idx_bh_project_interview_key_bq_project_id` (`project_id`),
  KEY `idx_bh_project_interview_key_bq_interview_id` (`project_interview_id`)
) ENGINE=InnoDB AUTO_INCREMENT=170 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='访谈 key BQ 与 KBQ Notes 表';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `bh_project_interview_minutes`
--

DROP TABLE IF EXISTS `bh_project_interview_minutes`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `bh_project_interview_minutes` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `project_id` bigint unsigned NOT NULL COMMENT '项目ID',
  `project_interview_id` bigint unsigned NOT NULL COMMENT '访谈ID',
  `outline_json` longtext COMMENT '智能纪要大纲JSON',
  `minutes_json` longtext COMMENT '智能纪要最终结果JSON',
  `status` varchar(32) NOT NULL DEFAULT 'pending' COMMENT '状态：pending/done/failed',
  `error_message` text COMMENT '错误信息',
  `generated_at` datetime DEFAULT NULL COMMENT '最近一次成功生成时间',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_bh_project_interview_minutes_interview_id` (`project_interview_id`),
  KEY `idx_bh_project_interview_minutes_project_id` (`project_id`),
  KEY `idx_bh_project_interview_minutes_status` (`status`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='访谈智能纪要表';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `bh_project_interview_notes`
--

DROP TABLE IF EXISTS `bh_project_interview_notes`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `bh_project_interview_notes` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `project_id` bigint NOT NULL,
  `project_interview_id` bigint NOT NULL,
  `question_id` bigint DEFAULT NULL,
  `intent_id` bigint NOT NULL,
  `note_json` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `confidence` decimal(5,4) DEFAULT NULL,
  `status` tinyint NOT NULL DEFAULT '0',
  `error_message` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_by` bigint DEFAULT NULL,
  `created_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `last_updated_by` bigint DEFAULT NULL,
  `last_updated_time` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_bh_notes_project_interview_question_intent` (`project_id`,`project_interview_id`,`question_id`,`intent_id`),
  KEY `idx_bh_notes_project` (`project_id`),
  KEY `idx_bh_notes_interview` (`project_interview_id`),
  KEY `idx_bh_notes_question` (`question_id`),
  KEY `idx_bh_notes_intent` (`intent_id`),
  CONSTRAINT `fk_bh_notes_intent` FOREIGN KEY (`intent_id`) REFERENCES `bh_question_intent` (`id`) ON UPDATE CASCADE,
  CONSTRAINT `fk_bh_notes_interview` FOREIGN KEY (`project_interview_id`) REFERENCES `bh_project_interview` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_bh_notes_project` FOREIGN KEY (`project_id`) REFERENCES `bh_project` (`id`) ON UPDATE CASCADE,
  CONSTRAINT `fk_bh_notes_question` FOREIGN KEY (`question_id`) REFERENCES `bh_project_question` (`id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `bh_project_interview_notes_chk_1` CHECK (json_valid(`note_json`))
) ENGINE=InnoDB AUTO_INCREMENT=171 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `bh_project_interview_summary`
--

DROP TABLE IF EXISTS `bh_project_interview_summary`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `bh_project_interview_summary` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `project_interview_id` bigint NOT NULL,
  `timestamp` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `speaker` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `text` longtext COLLATE utf8mb4_unicode_ci,
  `modify` tinyint NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  KEY `idx_bh_interview_summary_interview_id` (`project_interview_id`),
  CONSTRAINT `fk_bh_interview_summary_interview` FOREIGN KEY (`project_interview_id`) REFERENCES `bh_project_interview` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=2478 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `bh_project_notes_edit_log`
--

DROP TABLE IF EXISTS `bh_project_notes_edit_log`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `bh_project_notes_edit_log` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `notes_result_id` bigint NOT NULL,
  `editor_id` bigint NOT NULL,
  `action` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `before_json` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin,
  `after_json` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `quality_score` tinyint DEFAULT NULL,
  `comment` text COLLATE utf8mb4_unicode_ci,
  `created_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_bh_notes_edit_log_notes` (`notes_result_id`),
  CONSTRAINT `fk_bh_notes_edit_log_notes` FOREIGN KEY (`notes_result_id`) REFERENCES `bh_project_interview_notes` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `bh_project_notes_edit_log_chk_1` CHECK (json_valid(`before_json`)),
  CONSTRAINT `bh_project_notes_edit_log_chk_2` CHECK (json_valid(`after_json`))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `bh_project_question`
--

DROP TABLE IF EXISTS `bh_project_question`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `bh_project_question` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `project_interview_id` bigint NOT NULL,
  `question_order` int NOT NULL,
  `question_text` text COLLATE utf8mb4_unicode_ci NOT NULL,
  `question_type` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `research_phase` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `intent_id` bigint NOT NULL,
  `meta` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin,
  `created_by` bigint DEFAULT NULL,
  `created_time` datetime DEFAULT NULL,
  `last_updated_by` bigint DEFAULT NULL,
  `last_updated_time` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_bh_project_question_interview` (`project_interview_id`),
  KEY `idx_bh_project_question_intent` (`intent_id`),
  CONSTRAINT `fk_bh_project_question_intent` FOREIGN KEY (`intent_id`) REFERENCES `bh_question_intent` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_bh_project_question_interview` FOREIGN KEY (`project_interview_id`) REFERENCES `bh_project_interview` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `bh_project_question_chk_1` CHECK (json_valid(`meta`))
) ENGINE=InnoDB AUTO_INCREMENT=678 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `bh_question_intent`
--

DROP TABLE IF EXISTS `bh_question_intent`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `bh_question_intent` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `code` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `description` text COLLATE utf8mb4_unicode_ci,
  `schema_name` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `status` tinyint NOT NULL DEFAULT '1',
  `created_time` datetime DEFAULT NULL,
  `last_updated_time` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_bh_question_intent_code` (`code`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `bh_transcription_corrections`
--

DROP TABLE IF EXISTS `bh_transcription_corrections`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `bh_transcription_corrections` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `project_id` bigint unsigned NOT NULL COMMENT '项目ID',
  `project_interview_id` bigint unsigned NOT NULL COMMENT '访谈ID',
  `summary_id` bigint unsigned DEFAULT NULL COMMENT '被修改的summary记录ID',
  `wrong_text` varchar(1024) NOT NULL COMMENT '原始错误片段',
  `correct_text` varchar(1024) NOT NULL COMMENT '用户修正后的正确片段',
  `context_before` text COMMENT '修改片段前的上下文',
  `context_after` text COMMENT '修改片段后的上下文',
  `edit_type` varchar(64) DEFAULT NULL COMMENT '修改类型，如 term_replace / phrase_replace / sentence_rewrite',
  `confidence` decimal(5,4) DEFAULT NULL COMMENT '该规则的置信度',
  `usage_count` int NOT NULL DEFAULT '0' COMMENT '后续被复用的次数',
  `status` varchar(32) NOT NULL DEFAULT 'pending' COMMENT '状态：pending/approved/rejected',
  `created_by` bigint unsigned DEFAULT NULL COMMENT '操作人用户ID',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_bh_transcription_corrections_project_id` (`project_id`),
  KEY `idx_bh_transcription_corrections_interview_id` (`project_interview_id`),
  KEY `idx_bh_transcription_corrections_summary_id` (`summary_id`),
  KEY `idx_bh_transcription_corrections_status` (`status`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='访谈转录纠错学习表';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `bh_user`
--

DROP TABLE IF EXISTS `bh_user`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `bh_user` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '用户ID',
  `username` varchar(64) NOT NULL COMMENT '登录用户名',
  `password_hash` varchar(255) NOT NULL COMMENT '密码哈希，不存明文',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时\n  间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_bh_user_username` (`username`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='系统用户表';
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-05-09 14:50:34

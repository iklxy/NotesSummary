/*M!999999\- enable the sandbox mode */ 
-- MariaDB dump 10.19  Distrib 10.11.15-MariaDB, for Linux (aarch64)
--
-- Host: localhost    Database: benhealth
-- ------------------------------------------------------
-- Server version	10.11.15-MariaDB

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
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `name` varchar(255) NOT NULL,
  `keywords` text DEFAULT NULL,
  `core_problem` text DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_bh_project_name` (`name`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `bh_project_ca_table`
--

DROP TABLE IF EXISTS `bh_project_ca_table`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `bh_project_ca_table` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `project_id` bigint(20) NOT NULL,
  `ca_json` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL CHECK (json_valid(`ca_json`)),
  `status` varchar(32) NOT NULL DEFAULT 'pending',
  `error_message` text DEFAULT NULL,
  `generated_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `updated_at` datetime NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_bh_project_ca_table_project_id` (`project_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `bh_project_fewshot_sample`
--

DROP TABLE IF EXISTS `bh_project_fewshot_sample`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `bh_project_fewshot_sample` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `project_id` bigint(20) NOT NULL,
  `project_interview_id` bigint(20) DEFAULT NULL,
  `question_id` bigint(20) NOT NULL,
  `intent_id` bigint(20) NOT NULL,
  `notes_result_id` bigint(20) DEFAULT NULL,
  `sample_json` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL CHECK (json_valid(`sample_json`)),
  `quality_score` tinyint(4) NOT NULL,
  `source_kind` varchar(20) NOT NULL,
  `created_time` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `idx_bh_fewshot_project` (`project_id`),
  KEY `idx_bh_fewshot_interview` (`project_interview_id`),
  KEY `idx_bh_fewshot_question` (`question_id`),
  KEY `idx_bh_fewshot_intent` (`intent_id`),
  KEY `idx_bh_fewshot_notes` (`notes_result_id`),
  KEY `idx_bh_fewshot_quality` (`quality_score`)
) ENGINE=InnoDB AUTO_INCREMENT=6 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `bh_project_interview`
--

DROP TABLE IF EXISTS `bh_project_interview`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `bh_project_interview` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `parse_project_id` bigint(20) NOT NULL,
  `name` varchar(255) DEFAULT NULL,
  `keywords` text DEFAULT NULL,
  `core_problem` text DEFAULT NULL,
  `interview_date` datetime DEFAULT NULL,
  `file_id` varchar(100) DEFAULT NULL,
  `file_path` text DEFAULT NULL,
  `file_name` text DEFAULT NULL,
  `file_content` longtext DEFAULT NULL,
  `note_content` longtext DEFAULT NULL,
  `status` tinyint(3) DEFAULT NULL,
  `problem_answer` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`problem_answer`)),
  PRIMARY KEY (`id`),
  KEY `idx_bh_project_interview_project_id` (`parse_project_id`),
  CONSTRAINT `fk_bh_project_interview_project` FOREIGN KEY (`parse_project_id`) REFERENCES `bh_project` (`id`) ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=8 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `bh_project_interview_notes`
--

DROP TABLE IF EXISTS `bh_project_interview_notes`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `bh_project_interview_notes` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `project_id` bigint(20) NOT NULL,
  `project_interview_id` bigint(20) NOT NULL,
  `question_id` bigint(20) DEFAULT NULL,
  `intent_id` bigint(20) NOT NULL,
  `note_json` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL CHECK (json_valid(`note_json`)),
  `confidence` decimal(5,4) DEFAULT NULL,
  `status` tinyint(4) NOT NULL DEFAULT 0,
  `error_message` varchar(500) DEFAULT NULL,
  `created_by` bigint(20) DEFAULT NULL,
  `created_time` datetime NOT NULL DEFAULT current_timestamp(),
  `last_updated_by` bigint(20) DEFAULT NULL,
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
  CONSTRAINT `fk_bh_notes_question` FOREIGN KEY (`question_id`) REFERENCES `bh_project_question` (`id`) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=14 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `bh_project_interview_summary`
--

DROP TABLE IF EXISTS `bh_project_interview_summary`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `bh_project_interview_summary` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `project_interview_id` bigint(20) NOT NULL,
  `timestamp` varchar(32) DEFAULT NULL,
  `speaker` varchar(255) DEFAULT NULL,
  `text` longtext DEFAULT NULL,
  `modify` tinyint(2) NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  KEY `idx_bh_interview_summary_interview_id` (`project_interview_id`),
  CONSTRAINT `fk_bh_interview_summary_interview` FOREIGN KEY (`project_interview_id`) REFERENCES `bh_project_interview` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=1143 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `bh_project_notes_edit_log`
--

DROP TABLE IF EXISTS `bh_project_notes_edit_log`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `bh_project_notes_edit_log` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `notes_result_id` bigint(20) NOT NULL,
  `editor_id` bigint(20) NOT NULL,
  `action` varchar(50) NOT NULL,
  `before_json` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`before_json`)),
  `after_json` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL CHECK (json_valid(`after_json`)),
  `quality_score` tinyint(4) DEFAULT NULL,
  `comment` text DEFAULT NULL,
  `created_time` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `idx_bh_notes_edit_log_notes` (`notes_result_id`),
  CONSTRAINT `fk_bh_notes_edit_log_notes` FOREIGN KEY (`notes_result_id`) REFERENCES `bh_project_interview_notes` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `bh_project_question`
--

DROP TABLE IF EXISTS `bh_project_question`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `bh_project_question` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `project_interview_id` bigint(20) NOT NULL,
  `question_order` int(11) NOT NULL,
  `question_text` text NOT NULL,
  `question_type` varchar(50) NOT NULL,
  `research_phase` varchar(50) DEFAULT NULL,
  `intent_id` bigint(20) NOT NULL,
  `meta` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(`meta`)),
  `created_by` bigint(20) DEFAULT NULL,
  `created_time` datetime DEFAULT NULL,
  `last_updated_by` bigint(20) DEFAULT NULL,
  `last_updated_time` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_bh_project_question_interview` (`project_interview_id`),
  KEY `idx_bh_project_question_intent` (`intent_id`),
  CONSTRAINT `fk_bh_project_question_intent` FOREIGN KEY (`intent_id`) REFERENCES `bh_question_intent` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_bh_project_question_interview` FOREIGN KEY (`project_interview_id`) REFERENCES `bh_project_interview` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=18 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `bh_question_intent`
--

DROP TABLE IF EXISTS `bh_question_intent`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `bh_question_intent` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `code` varchar(100) NOT NULL,
  `name` varchar(255) DEFAULT NULL,
  `description` text DEFAULT NULL,
  `schema_name` varchar(100) DEFAULT NULL,
  `status` tinyint(4) NOT NULL DEFAULT 1,
  `created_time` datetime DEFAULT NULL,
  `last_updated_time` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_bh_question_intent_code` (`code`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-04-19 19:01:51

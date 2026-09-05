# Milvus 向量数据库本地部署与运维手册

## 部署组件

Milvus Standalone 通常依赖三个核心组件：Milvus 服务本体、etcd 和对象存储。etcd 负责元数据管理，对象存储负责保存向量索引和数据文件。本地开发环境可以使用 Docker Compose 同时启动 Milvus、etcd、MinIO 和 Redis。生产环境则需要根据数据规模和查询并发选择 Standalone 或 Cluster 模式。

## 常见端口

Milvus 默认服务端口是 19530，Web 或 metrics 端口通常是 9091。MinIO 默认端口为 9000，控制台端口为 9001。Redis 默认端口为 6379。Windows 环境可能存在端口预留问题，如果 6379、9091 或 5174 被系统保留，可以映射到 16379、19091 或 15174 等更高端口。

## Collection 设计

RAG 场景建议在 collection 中保存 chunk_id、text、source、doc_type、parent_id、parent_index、child_index、metadata_json 和 embedding 字段。embedding 使用 FLOAT_VECTOR，维度必须与嵌入模型输出维度一致。相似度度量可以选择 COSINE、IP 或 L2，其中 COSINE 更常用于文本语义检索。

## 高并发注意事项

高并发检索时，Milvus 适合作为向量召回层，但不适合替代完整业务数据库。任务状态、用户信息、报告记录和审计日志仍建议保存在 PostgreSQL、MySQL 或 SQLite 中。Redis 可用于缓存、任务队列和 SSE 状态同步。对于写入较频繁的知识库，需要控制批量插入大小，并将文档解析、Embedding 和索引写入拆成异步任务。

## 排障建议

如果 RAG 检索为空，应先检查 collection 是否存在、文档是否重新导入、Milvus 服务端口是否可达，以及后端配置中的 MILVUS_URI 是否正确。切换向量后端后，旧 ChromaDB 数据不会自动出现在 Milvus 中，需要重新导入或执行迁移脚本。

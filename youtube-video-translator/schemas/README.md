# JSON Schema Registry

7 个 schema 文件定义了 `temp/` 目录下所有中间产物的契约。

## 文件清单

| Schema | 对应产物 | 关键约束 |
|---|---|---|
| `metadata.schema.json` | `temp/metadata.json` | video_id/title/duration/has_official_caption/caption_languages 必填 |
| `caption_plan.schema.json` | `temp/caption_plan.json` | source ∈ {official, asr}；official 时 input_srt 非 null，asr 时为 null |
| `source_segments.schema.json` | `temp/source_segments.json` | **时间轴不可丢失**：每条 segment 必须含 start/end/text；两条 caption 路径的输出 schema 完全一致 |
| `asr_segments.schema.json` | `temp/asr_segments.json` | 每条 segment 必须含 start/end/text（时间轴不可丢失） |
| `chunks.schema.json` | `temp/chunks.json` | chunk_id/segment_ids/start/end/text/status 必填；glossary_terms 可选 |
| `translation_state.schema.json` | `temp/translation_state.json` | model_id/provider/runner/prompt_version/glossary_hash/chunking_hash/source_hash/validator_version 组成 translation contract；任一变化则缓存失效 |
| `subtitle_manifest.schema.json` | `temp/subtitle_manifest.json` | **时间轴不可丢失**：start/end 必须与 source_segments 完全一致（误差 < 0.1s） |

## 校验

```bash
# 校验所有 schema 文件本身（是否为合法 JSON Schema Draft7）
python3 schemas/validate_schemas.py

# 用 jsonschema 校验某个产物文件
python3 -c "
import jsonschema, json
schema = json.load(open('schemas/metadata.schema.json'))
instance = json.load(open('translations/[VIDEO_ID]/temp/metadata.json'))
jsonschema.validate(instance, schema)
print('OK')
"
```

## 时轴不可丢失规则

所有带字幕的 schema（source_segments / asr_segments / subtitle_manifest）都有 `start` 和 `end` 字段，这些字段：
- **不得删除或重命名**
- **不得改变数据类型**（必须是 float seconds）
- **不得通过任何中间步骤四舍五入**（对齐时误差 < 0.1s）
- **不得用文本时间轴字符串替代 float**

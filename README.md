grok改的，改成Verified on Windows了，但是1 Windows-only test skipped on macOS (that case requires a real Windows filesystem). 

## 高优先级

**1. NFR4：Windows 实机验证仍缺**  
SRS/Design 声明目标平台是 Windows；README 写明 macOS 验证、Windows 待测。  
建议：在真 Windows 上跑启动命令、全量 `unittest`、coverage，并确认非法文件名保存失败不改脏数据。

---

## 中优先级

| # | 问题 | 位置 | 建议改法 |
|---|------|------|----------|
| 1 | `run()` 忽略 `execute()` 返回值，与 Design §8 契约不一致 | `cli/controller.py` 51–55、101–165 | 改为 `if not self.execute(...): break`，或明确文档改为“仅副作用” |
| 2 | Controller 调用 View 私有方法 | `controller.py:47` → `view._closed_input()` | 升为公开 API，例如 `report_closed_input_with_unsaved_changes()` |
| 3 | `OverwriteRequiredError` ⊂ `PersistenceError`，通用 handler 可能叠错误提示 | `controller.py:71–76` vs `_save` 81–85 | `run()` 里先单独处理 `OverwriteRequiredError`，再处理一般 `PersistenceError` |
| 4 | create 缺字段提示被字母排序，EVENT 变成 `alarm, description, start` | `cli/parser.py:133–136` | `_CREATE_FIELDS` 用固定顺序 tuple，错误信息按 Design 字段序输出 |
| 5 | CLI / model 两套引号转义逻辑易漂移 | `cli/literals.py` 与 `model/search.py` | 抽共享解码到 `model` 或独立无 I/O 模块，两边共用 |
| 6 | `normalize_text` 错误标签固定为 `"Text"` | `model/validation.py:38–47` | 增加 `label` 参数，按字段传入 description/name/address |

---

## 低优先级

1. **时间格式化重复**：`cli/view.py` 与 `model/persistence.py` → 抽 `format_time(dt)`  
2. **跨模块私有导入**：`_TEXT_FIELDS` / `_LINE_BREAKS` → 升为公开常量  
3. **表达式解析仍递归**：靠 `RecursionError`；求值已迭代 → 解析也可迭代化  
4. **覆盖率假阴性**：`search.py` 深递归与 `validation.py` TYPE_CHECKING 行 → 在覆盖率说明里标注即可，不是功能 bug  
5. **`CriteriaRegistry.all()`** 显式按 `C1,C2…` 数字排序，减少对 view 二次排序的依赖  

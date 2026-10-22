# php2shell-oom-to-uaf

隔離環境中研究 CVE-2026-109618 / CVE-2026-109619（PHP 核心的兩個未驗證身分 RCE）
的**觸發階段**：一個 multipart POST 如何在任何應用程式碼執行之前，把 PHP 的請求
解析器推到 out-of-memory。

> 這是實驗儀器，不是利用程式。它不產生任何程式碼執行 payload，不控制釋放後的記憶體
> 要用來做什麼，也不試圖達成 RCE。目的是量測「OOM 發生在哪裡、以什麼形式出現」。

## 為什麼要看這個

漏洞本身在 Zend 引擎的錯誤處理模型，不在 session 或上傳功能。修補 commit
（`01a40e89fbfc499936e3b05888d8f00bfde886df`，2026-10-18 15:26 UTC）改了 300 個檔案、
+10,759/−988 行，其中 206 個 `.phpt`、196 個是新增的 `oom_*` 測試——那些測試名稱就是
維護者眼中的觸發面地圖。這個專案把地圖上「multipart 解析」那一格拿出來實測。

## 環境

| 用途 | 影像 |
|---|---|
| 漏洞版 | `php:8.4.26-cli`、`php:8.4.26-apache`（mod_php） |
| 修補版 | `php:8.4.27-cli`、`php:8.4.27-apache` |

兩個版本其餘變數完全相同。容器一律 `--network none`、記憶體上限、lab 目錄唯讀掛載、
跑完即刪。所有動作都在容器內完成，host 只負責 `docker run`。

## 執行

```bash
# 短生命週期 SAPI：每個請求一個新程序
docker run --rm --network none --memory 512m -v "$PWD/lab":/lab:ro \
  php:8.4.26-cli bash /lab/inside.sh huge_field_name 6 8M

# 長生命週期 SAPI（mod_php）：解析器在任何應用程式碼之前執行
docker run --rm --network none --memory 640m -v "$PWD/lab":/lab:ro \
  php:8.4.26-apache bash /lab/modphp.sh huge_field_name 6 8M

# 堆積填充掃描：改變 $_FILES 註冊當下的堆積狀態
docker run --rm --network none --memory 640m -v "$PWD/lab":/lab:ro \
  php:8.4.27-apache bash /lab/modscan.sh 8M 200 1400 200

# 原廠 limit 下還能不能 OOM
docker run --rm --network none --memory 768m -v "$PWD/lab":/lab:ro \
  php:8.4.26-apache bash /lab/defaults.sh 60000 128M 8M
```

`lab/mkbody.php` 產生 body（形狀取自上游新增的 `tests/basic/oom_rfc1867_*.phpt`）：

| shape | 讓什麼變重 |
|---|---|
| `huge_field_name` | 欄位名稱本身必須被解析器保留 |
| `huge_array_name` | `name="<X>[k]"`，param／abuf／array_index 是三份拷貝 |
| `huge_filename` | 重量落在 `$_FILES` 的 `[full_path]` |
| `many_parts` | `$_FILES` 這張表本身就是那個配置 |
| `padded_registration` | 先填滿堆積，讓下一次配置在註冊中途失敗 |

## 觀察到什麼（`results/`）

**確認（等級一：觸發異常）**

- 單一 multipart POST，在 `post_max_size`／`upload_max_filesize`／`max_input_vars`
  都設得很大的情況下，可以把請求解析器推到 OOM。8M limit 下 6,291,580 bytes 的 body
  就夠，回應是 `Allowed memory size of 8388608 bytes exhausted`。
- 錯誤位置是 `in Unknown on line 0`——**表示 OOM 發生在腳本被執行之前**，與公告所說
  「在任何應用程式碼開始執行前」一致。目標腳本從未輸出任何東西。
- 在 CGI、cli-server、mod_php 三種 SAPI 都重現。
- 兩個版本在這一階段的行為一致：都是乾淨的 fatal error，worker 全部存活，沒有
  segmentation fault。

**沒有觀察到什麼（不要冒充）**

- 沒有狀態損毀、沒有跨請求殘留、沒有記憶體洩漏、沒有 RCE。
- `8.4.26` 與 `8.4.27` 在我跑過的所有形狀與所有 pad（200–1400 KB）下**沒有差異**。
  填充掃描兩版的 `http`／`worker`／第二次請求／segfault 計數完全相同。
- 原廠 limits 下（`memory_limit=128M`、`post_max_size=8M`），7.82 MiB / 60,000 個
  part 的 body **會進到應用程式層**，沒有 OOM。
- PHP 8.4 的 `max_multipart_body_parts` 預設是 **1020**；超過就報
  `Multipart body parts limit exceeded 1020`，所以「大量 part」這條路在原廠設定下本來
  就有上限。

也就是說：這裡只做到「觸發異常」。從觸發走到記憶體錯誤再到 RCE，需要遠比
「讓一次配置失敗」精確的堆積安排，本專案沒有做到，也不宣稱做到。

## 方法論陷阱（踩過的）

- **client 會繼承 server 的 ini。** mod_php 的設定寫在 `/usr/local/etc/php/conf.d/`，
  同一個容器裡負責發送請求的 `php post.php` 也讀同一份，結果 6 MB body 讓 *client*
  先 OOM，看起來像 server 的錯誤。實際上那次請求根本沒送出去。修法：client 一律
  `php -n -d memory_limit=256M`，不要繼承 server 的低上限。
- **CGI 模式看不出跨請求問題。** 每個請求都是新程序，前一次 bailout 留下的狀態沒有
  機會被下一個請求讀到。要驗跨請求必須用長期存活的 SAPI。
- **只看「有沒有噴錯」不夠。** 兩版都會噴 OOM；要比的是 exit code、worker 存活、
  第二次回應、以及 segfault 紀錄。

## 這個專案不是什麼

不提供 weaponized exploit、不提供可對實際伺服器使用的完整利用、不提供 payload。
修補、偵測與防禦請看 `results/` 的量測與部落格文章的防守段。

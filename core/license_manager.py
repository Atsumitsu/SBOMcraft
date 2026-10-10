# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj

import os
import json
import urllib.request
from datetime import datetime

class SPDXLicenseManager:
    """SPDXライセンスリストおよび例外リストのローカル管理および公式からのダウンロードを行うマネージャー"""
    
    SPDX_JSON_URL = "https://spdx.org/licenses/licenses.json"
    SPDX_EXCEPTIONS_JSON_URL = "https://spdx.org/licenses/exceptions.json" # ← 追加
    
    def __init__(self, storage_dir: str = ".cache"):
        self.storage_dir = storage_dir
        self.file_path = os.path.join(self.storage_dir, "spdx_licenses.json")
        self.exception_file_path = os.path.join(self.storage_dir, "spdx_exceptions.json") # ← 追加
        
        self._cached_data = None
        self._cached_exceptions_data = None # ← 追加
        self._valid_license_ids = set()
        self._valid_exception_ids = set() # ← 追加
        
        self.load_local_cache()

    def get_metadata(self) -> dict:
        """ローカルに保存されているリストのバージョンや日付、ステータス、件数を返す"""
        if not os.path.exists(self.file_path):
            return {
                "exists": False,
                "version": "未ダウンロード",
                "released_date": "-",
                "count": 0,
                "exc_count": 0
            }
        
        try:
            if not self._cached_data:
                self.load_local_cache()
                
            if self._cached_data:
                version = self._cached_data.get("licenseListVersion", "不明")
                licenses = self._cached_data.get("licenses", [])
                exceptions = self._cached_exceptions_data.get("exceptions", []) if self._cached_exceptions_data else []
                
                mtime = os.path.getmtime(self.file_path)
                file_date = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
                
                return {
                    "exists": True,
                    "version": version,
                    "released_date": file_date,
                    "count": len(licenses),
                    "exc_count": len(exceptions)
                }
        except Exception as e:
            print(f"[Error] Metadata read failed: {e}")
            
        return {
            "exists": True,
            "version": "読込エラー",
            "released_date": "-",
            "count": 0,
            "exc_count": 0
        }

    def load_local_cache(self) -> bool:
        """ローカルに保存された JSON キャッシュをメモリ上にロードする"""
        success = True
        
        # 1. ライセンスJSONのロード
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    self._cached_data = json.load(f)
                self._valid_license_ids.clear()
                for lic in self._cached_data.get("licenses", []):
                    if lic_id := lic.get("licenseId"):
                        self._valid_license_ids.add(lic_id)
            except Exception as e:
                print(f"[Error] Local license cache load failed: {e}")
                success = False

        # 2. 例外JSONのロード（追加）
        if os.path.exists(self.exception_file_path):
            try:
                with open(self.exception_file_path, 'r', encoding='utf-8') as f:
                    self._cached_exceptions_data = json.load(f)
                self._valid_exception_ids.clear()
                for exc in self._cached_exceptions_data.get("exceptions", []):
                    if exc_id := exc.get("licenseExceptionId"):
                        self._valid_exception_ids.add(exc_id)
            except Exception as e:
                print(f"[Error] Local exception cache load failed: {e}")

        return success

    def download_latest_list(self) -> tuple[bool, str]:
        """公式から最新の SPDX ライセンスリストおよび例外リストをダウンロードして保存する"""
        try:
            os.makedirs(self.storage_dir, exist_ok=True)
            headers = {'User-Agent': 'SBOMcraft-LicenseChecker/1.0'}
            
            # 1. ライセンスリストのダウンロード
            req_lic = urllib.request.Request(self.SPDX_JSON_URL, headers=headers)
            with urllib.request.urlopen(req_lic, timeout=10) as response:
                if response.status == 200:
                    raw_data = response.read()
                    json_data = json.loads(raw_data.decode('utf-8'))
                    
                    with open(self.file_path, 'wb') as f:
                        f.write(raw_data)
                    version = json_data.get("licenseListVersion", "unknown")
                else:
                    return False, f"サーバー応答エラー (licenses): HTTP {response.status}"

            # 2. 例外リストのダウンロード（追加）
            try:
                req_exc = urllib.request.Request(self.SPDX_EXCEPTIONS_JSON_URL, headers=headers)
                with urllib.request.urlopen(req_exc, timeout=10) as res_exc:
                    if res_exc.status == 200:
                        raw_exc_data = res_exc.read()
                        with open(self.exception_file_path, 'wb') as f:
                            f.write(raw_exc_data)
            except Exception as exc_err:
                print(f"[Warning] Exceptions download failed: {exc_err}")

            # キャッシュを再読込
            self.load_local_cache()
            return True, f"正常にダウンロードしました (Version: {version})"
                
        except Exception as e:
            return False, f"ダウンロードに失敗しました: {str(e)}"

    def is_valid_spdx_id(self, license_id: str) -> bool:
        """指定された文字列が有効な SPDX ライセンス ID かどうかを判定する"""
        if not license_id:
            return False
        return license_id in self._valid_license_ids

    def is_valid_exception_id(self, exception_id: str) -> bool:
        """指定された文字列が有効な SPDX 例外 ID かどうかを判定する（追加）"""
        if not exception_id:
            return False
        return exception_id in self._valid_exception_ids
    
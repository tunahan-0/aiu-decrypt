import asyncio
import subprocess
import base64
import os
import shutil
import tempfile
import uuid
import zipfile
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# --------------
# Veri Yapıları
# --------------
@dataclass
class SubtitleFile:
    path: str
    language: str


@dataclass
class DecryptedFiles:
    video_path: Optional[str] = None
    subtitle_files: List[SubtitleFile] = field(default_factory=list)

# ---------------
# Şifre Anahtarı
# ---------------
class EncryptionHelper:

    @staticmethod
    def get_encryption_key() -> bytes:
        p1 = base64.b64decode("SVVN").decode("ascii")  # "IUM"
        p2 = base64.b64decode("NDY3QQ==").decode("ascii")  # "467A"
        p3 = base64.b64decode("NDM2NTE=").decode("ascii")  # "43651"

        key_bytes = (p1 + p2 + p3).encode("utf-8")

        if len(key_bytes) < 32:
            key_bytes = key_bytes.ljust(32, b"\x00")
        elif len(key_bytes) > 32:
            key_bytes = key_bytes[:32]

        return key_bytes

# --------------------
# Şifre Çözme Servisi
# --------------------
class PackageDecryptionService:

    async def decrypt_episode_async(
        self, encrypted_file_path: str
    ) -> DecryptedFiles:
        if not encrypted_file_path or not os.path.exists(encrypted_file_path):
            raise FileNotFoundError(
                f"Şifreli dosya bulunamadı: {encrypted_file_path}"
            )

        file_path_obj = Path(encrypted_file_path)
        episode_id = file_path_obj.stem
        file_size_mb = file_path_obj.stat().st_size / (1024 * 1024)

        print(
            f"Paket çözülüyor: {episode_id} ({file_size_mb:.2f} MB)"
        )

        temp_dir = tempfile.gettempdir()
        return await self._decrypt_to_temp_file_then_extract(
            encrypted_file_path, temp_dir
        )

    async def _decrypt_to_temp_file_then_extract(
        self, encrypted_file_path: str, temp_dir: str
    ) -> DecryptedFiles:
        fd, temp_decrypted_file = tempfile.mkstemp(suffix=".zip")
        os.close(fd)

        try:
            # 1. AES Şifresini Çöz
            await asyncio.to_thread(
                self._aes_decrypt_file, encrypted_file_path, temp_decrypted_file
            )

            # 2. ZIP Arşivini Aç ve Dosyaları Ayıkla
            return await asyncio.to_thread(
                self._extract_zip, temp_decrypted_file, temp_dir
            )

        finally:
            if os.path.exists(temp_decrypted_file):
                try:
                    os.remove(temp_decrypted_file)
                except Exception:
                    pass

    def _aes_decrypt_file(self, src_path: str, dest_path: str) -> None:
        key = EncryptionHelper.get_encryption_key()

        with open(src_path, "rb") as f_in:
            iv = f_in.read(16)
            if len(iv) != 16:
                raise ValueError(
                    f"Geçersiz IV boyutu: {len(iv)}/16 bayt okundu."
                )

            encrypted_data = f_in.read()

        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        decrypted_data = (
            decryptor.update(encrypted_data) + decryptor.finalize()
        )

        unpadder = padding.PKCS7(128).unpadder()
        final_data = unpadder.update(decrypted_data) + unpadder.finalize()

        with open(dest_path, "wb") as f_out:
            f_out.write(final_data)

    def _extract_zip(
        self, decrypted_zip_path: str, target_dir: str
    ) -> DecryptedFiles:
        result = DecryptedFiles()

        with zipfile.ZipFile(decrypted_zip_path, "r") as archive:
            for entry_info in archive.infolist():
                if entry_info.is_dir():
                    continue

                entry_name = entry_info.filename
                ext = ".vtt" if entry_name.startswith("subtitle_") else ""
                random_id = str(uuid.uuid4())
                output_file_path = os.path.join(target_dir, f"{random_id}{ext}")

                with archive.open(entry_info) as source, open(
                    output_file_path, "wb"
                ) as target:
                    shutil.copyfileobj(source, target, length=32768)

                if entry_name == "video":
                    result.video_path = output_file_path
                elif entry_name.startswith("subtitle_"):
                    parts = entry_name.split("_")
                    language = (
                        "_".join(parts[2:]) if len(parts) >= 3 else "Unknown"
                    )
                    result.subtitle_files.append(
                        SubtitleFile(path=output_file_path, language=language)
                    )

        return result
    
    async def embed_subtitles_async(
        self, video_path: str, subtitle_files: list, output_mkv_path: str, ffmpeg_path: str
    ) -> tuple[bool, str]:
        """FFmpeg kullanarak videoya altyazıları ekler ve Türkçe altyazıyı varsayılan (default) yapar."""
        def _run_ffmpeg():
            exe = Path(ffmpeg_path if ffmpeg_path else "ffmpeg").as_posix()
            v_path = Path(video_path).as_posix()
            out_path = Path(output_mkv_path).as_posix()

            cmd = [exe, "-y", "-i", v_path]

            # 1. Altyazı dosya girdilerini ekle
            for sub in subtitle_files:
                sub_file_path = sub.path if hasattr(sub, "path") else sub
                cmd.extend(["-i", Path(sub_file_path).as_posix()])

            # 2. Sadece Video (0:v) ve Ses (0:a) akışlarını haritala
            cmd.extend(["-map", "0:v", "-map", "0:a"])

            # 3. Türkçe Altyazı İndeksini Bul
            default_sub_index = 0  # Bulunamazsa ilk altyazıyı varsayılan yap

            for idx, sub in enumerate(subtitle_files):
                raw_lang = (sub.language if hasattr(sub, "language") else "").lower()
                if any(term in raw_lang for term in ["türkçe", "turkce", "tr", "turkish", "tur"]):
                    default_sub_index = idx
                    break

            # 4. Akışları bağla, dil ISO kodlarını ve varsayılan bayrağını ata
            for i, sub in enumerate(subtitle_files):
                raw_lang = (sub.language if hasattr(sub, "language") else "").lower()
                
                # FFmpeg için ISO 639-2 dil kodunu belirle
                if any(term in raw_lang for term in ["türkçe", "turkce", "tr", "turkish", "tur"]):
                    iso_lang = "tur"
                elif "en" in raw_lang or "eng" in raw_lang or "english" in raw_lang:
                    iso_lang = "eng"
                else:
                    iso_lang = "und"  # Undefined (Bilinmeyen)

                # Altyazı akışını haritala
                cmd.extend(["-map", f"{i+1}:s"])
                
                # Dil metadatasını ekle (Oynatıcı menüsünde dilin görünmesi için)
                cmd.extend([f"-metadata:s:s:{i}", f"language={iso_lang}"])
                cmd.extend([f"-metadata:s:s:{i}", f"title={sub.language}"])

                # Türkçe (veya seçilen) altyazıyı birincil yap
                if i == default_sub_index:
                    cmd.extend([f"-disposition:s:{i}", "default"])
                else:
                    cmd.extend([f"-disposition:s:{i}", "0"])

            # Kalite kaybı olmadan kopyala, altyazıları srt olarak MKV içine göm
            cmd.extend(["-c:v", "copy", "-c:a", "copy", "-c:s", "srt", out_path])

            # Windows'ta ffmpeg için konsol penceresini gizle
            creationflags = 0
            startupinfo = None
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE

            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                text=True,
                check=True,
                creationflags=creationflags,
                startupinfo=startupinfo,
            )
            return result
        
        try:
            await asyncio.to_thread(_run_ffmpeg)
            return True, ""
        except subprocess.CalledProcessError as cpe:
            err_msg = cpe.stderr.strip() if cpe.stderr else str(cpe)
            return False, err_msg
        except Exception as ex:
            return False, str(ex)
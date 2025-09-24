# videostreaming
steam via fastapi to huge video file  for H5P


## สำหรับเอาไป stream 
- moodle มีส่วนการใช้ H5P ที่ต้องอัพตรงหรือ ใช้ URL link
- ทำให้อัพไฟล์ใหญ่ๆ ไม่ได้
- ตัวนี้จะสร้าง การเชื่อมต่อโดย ติดตั้ง ffmpeg ไว้ก่อน แล้วจะใช้งานผ่าน ffmpeg
- เรียกผ่าน API ได้เลย


# 🛠️ คู่มือติดตั้ง Software พื้นฐาน Windows Server 2019

### สามารถใช้ผ่าน reverse-proxy โดยไม่ต้องติดตั้ง mod_wsgi ได้

## 📋 สิ่งที่ต้องติดตั้ง
1. Python 3.9+
2. mod_wsgi สำหรับ Apache
3. FFmpeg สำหรับ video processing

---

## 🐍 1. ติดตั้ง Python 3.9+

### วิธีที่ 1: ติดตั้งจาก Official Website (แนะนำ)

#### 1.1 ดาวน์โหลด Python
- เข้า https://www.python.org/downloads/windows/
- เลือก **Python 3.11.x** (เวอร์ชันล่าสุด stable)
- คลิก **Windows installer (64-bit)** 

#### 1.2 ติดตั้ง Python
```cmd
# ดับเบิ้ลคลิกไฟล์ .exe ที่ดาวน์โหลดมา
# ✅ ติก "Add Python to PATH"  <- สำคัญมาก!
# ✅ ติก "Install for all users"
# เลือก "Customize installation"
# ✅ ติก "pip" 
# ✅ ติก "py launcher"
# ✅ ติก "Add Python to environment variables"
# Next -> Install
```

#### 1.3 ตรวจสอบการติดตั้ง
```cmd
# เปิด Command Prompt (Run as Administrator)
python --version
# ควรแสดง: Python 3.11.x

pip --version
# ควรแสดง: pip 23.x.x
```

### วิธีที่ 2: ใช้ Chocolatey (สำหรับคนที่ชอบ command line)

#### 2.1 ติดตั้ง Chocolatey ก่อน
```powershell
# เปิด PowerShell (Run as Administrator)
Set-ExecutionPolicy Bypass -Scope Process -Force
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
```

#### 2.2 ติดตั้ง Python ด้วย Choco
```cmd
# Command Prompt (Run as Administrator)
choco install python
# รอสักครู่...

# ตรวจสอบ
python --version
pip --version
```

---

## 🌐 2. ติดตั้ง mod_wsgi สำหรับ Apache

### 2.1 ติดตั้ง mod_wsgi ผ่าน pip
```cmd
# Command Prompt (Run as Administrator)
pip install mod_wsgi
```

### 2.2 สร้างไฟล์ mod_wsgi.so
```cmd
# Generate mod_wsgi configuration
mod_wsgi-express module-config

# จะได้ผลลัพธ์คล้ายๆ นี้:
# LoadModule wsgi_module "C:/Python311/lib/site-packages/mod_wsgi/server/mod_wsgi.cp311-win_amd64.pyd"
# WSGIPythonHome "C:/Python311"
```

### 2.3 เพิ่ม mod_wsgi ใน Apache
แก้ไขไฟล์ `C:\Apache24\conf\httpd.conf`:
```apache
# เพิ่มบรรทัดนี้ (ปรับ path ให้ตรงกับผลลัพธ์จากข้างบน)
LoadModule wsgi_module "C:/Python311/lib/site-packages/mod_wsgi/server/mod_wsgi.cp311-win_amd64.pyd"
WSGIPythonHome "C:/Python311"
```

### 2.4 ทดสอบ Apache
```cmd
# Restart Apache
net stop Apache2.4
net start Apache2.4

# ตรวจสอบ error log ถ้ามี
type "C:\Apache24\logs\error.log"
```

---

## 🎬 3. ติดตั้ง FFmpeg สำหรับ video processing

### วิธีที่ 1: Manual Installation (แนะนำ)

#### 3.1 ดาวน์โหลด FFmpeg
- เข้า https://www.gyan.dev/ffmpeg/builds/
- เลือก **release builds**
- คลิก **ffmpeg-release-essentials.zip**

#### 3.2 แตกไฟล์และติดตั้ง
```cmd
# แตกไฟล์ไปยัง C:\ffmpeg\
# โครงสร้างที่ได้:
# C:\ffmpeg\
# ├── bin\
# │   ├── ffmpeg.exe
# │   ├── ffprobe.exe
# │   └── ffplay.exe
# ├── doc\
# └── presets\
```

#### 3.3 เพิ่ม FFmpeg ใน PATH
```cmd
# วิธีที่ 1: ผ่าน GUI
# 1. Right-click "This PC" -> Properties
# 2. Advanced system settings -> Environment Variables
# 3. ใน System Variables หา "Path" -> Edit
# 4. New -> เพิ่ม "C:\ffmpeg\bin"
# 5. OK ทุก dialog

# วิธีที่ 2: ผ่าน Command Line (Run as Administrator)
setx /M PATH "%PATH%;C:\ffmpeg\bin"
```

#### 3.4 ทดสอบการติดตั้ง
```cmd
# เปิด Command Prompt ใหม่
ffmpeg -version
# ควรแสดงข้อมูลเวอร์ชันของ FFmpeg

ffprobe -version
# ควรแสดงข้อมูลเวอร์ชันของ FFprobe
```

### วิธีที่ 2: ใช้ Chocolatey
```cmd
# Command Prompt (Run as Administrator)
choco install ffmpeg

# ตรวจสอบ
ffmpeg -version
```

---

## ✅ 4. การตรวจสอบการติดตั้งทั้งหมด

### 4.1 สร้างไฟล์ทดสอบ
สร้างไฟล์ `test_installation.py`:
```python
#!/usr/bin/env python3
import sys
import subprocess
import importlib.util

def test_python():
    print(f"🐍 Python Version: {sys.version}")
    print(f"📁 Python Path: {sys.executable}")
    return True

def test_pip():
    try:
        result = subprocess.run(['pip', '--version'], capture_output=True, text=True)
        print(f"📦 Pip: {result.stdout.strip()}")
        return True
    except:
        print("❌ Pip not found")
        return False

def test_mod_wsgi():
    try:
        import mod_wsgi
        print(f"🌐 mod_wsgi: Available")
        result = subprocess.run(['mod_wsgi-express', '--version'], capture_output=True, text=True)
        print(f"🌐 mod_wsgi-express: {result.stdout.strip()}")
        return True
    except:
        print("❌ mod_wsgi not found")
        return False

def test_ffmpeg():
    try:
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True, timeout=10)
        lines = result.stdout.split('\n')
        print(f"🎬 FFmpeg: {lines[0]}")
        return True
    except:
        print("❌ FFmpeg not found")
        return False

def test_ffprobe():
    try:
        result = subprocess.run(['ffprobe', '-version'], capture_output=True, text=True, timeout=10)
        lines = result.stdout.split('\n')
        print(f"🔍 FFprobe: {lines[0]}")
        return True
    except:
        print("❌ FFprobe not found")
        return False

if __name__ == "__main__":
    print("🛠️ Testing Software Installation")
    print("=" * 50)
    
    tests = [
        ("Python", test_python),
        ("Pip", test_pip), 
        ("mod_wsgi", test_mod_wsgi),
        ("FFmpeg", test_ffmpeg),
        ("FFprobe", test_ffprobe)
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append(result)
        except Exception as e:
            print(f"❌ {name}: Error - {e}")
            results.append(False)
        print()
    
    print("=" * 50)
    if all(results):
        print("🎉 All software installed successfully!")
    else:
        print("⚠️  Some software missing. Please check installation.")
    
    input("Press Enter to exit...")
```

### 4.2 รันการทดสอบ
```cmd
cd C:\
python test_installation.py
```

---

## 🚨 Troubleshooting

### ปัญหา Python
```cmd
# ถ้า python command ไม่พบ
py --version
python3 --version

# ถ้ายังไม่ได้ ให้ reinstall Python และติก "Add to PATH"
```

### ปัญหา mod_wsgi
```cmd
# ถ้า pip install mod_wsgi ล้มเหลว
pip install --upgrade pip
pip install wheel
pip install mod_wsgi

# หรือลองเวอร์ชันเก่า
pip install mod_wsgi==4.9.4
```

### ปัญหา FFmpeg
```cmd
# ถ้า PATH ไม่ทำงาน ให้ใช้ full path
C:\ffmpeg\bin\ffmpeg.exe -version

# หรือ copy ffmpeg.exe ไปใน System32
copy "C:\ffmpeg\bin\ffmpeg.exe" "C:\Windows\System32\"
copy "C:\ffmpeg\bin\ffprobe.exe" "C:\Windows\System32\"
```

### ปัญหา Apache + mod_wsgi
```cmd
# ตรวจสอบ Apache error log
type "C:\Apache24\logs\error.log"

# ทดสอบ Apache syntax
C:\Apache24\bin\httpd.exe -t

# ถ้า mod_wsgi ใช้ไม่ได้ ให้ตรวจสอบ Python version compatibility
```

---

## 📝 สรุป Commands ทั้งหมด

```cmd
REM 1. Install Python (manual download + install)

REM 2. Install mod_wsgi
pip install mod_wsgi
mod_wsgi-express module-config

REM 3. Install FFmpeg (manual download + PATH setup)

REM 4. Test everything
python test_installation.py

REM 5. Install Python packages for video app
pip install flask flask-cors

REM Ready to go! 🚀
```


## apache reverse proxy
```
    # ================== Reverse proxy for Flask video-streaming ==================
    # ให้ /video-streaming/ ชี้หน้า index ของ Flask
    ProxyPreserveHost On
    SSLProxyEngine On

    # ปรับ timeout สำหรับไฟล์ใหญ่/สตรีม
    ProxyTimeout 600
    TimeOut 600

    # MIME ที่จำเป็นสำหรับ HLS
    AddType application/vnd.apple.mpegURL .m3u8
    AddType video/MP2T                      .ts

    # ไม่บีบอัดวิดีโอ/สตรีม
    SetEnvIfNoCase Request_URI "\.(mp4|m4v|m3u8|ts|webm)$" no-gzip=1

    # Security headers พื้นฐาน
    Header always set X-Content-Type-Options "nosniff"

    # ถ้าเข้ามาที่ /video-streaming (ไม่มี / ท้าย) ให้เติม /
    RedirectMatch 301 ^/video-streaming$ /video-streaming/

    # --- เมานท์แอปที่ prefix /video-streaming/ ---
    ProxyPass        /video-streaming/  http://127.0.0.1:5000/
    ProxyPassReverse /video-streaming/  http://127.0.0.1:5000/

    # --- เมานท์เส้นทางที่หน้าเว็บเรียกแบบ absolute (/api, /hls, /player_path, /hlsplayer) ---
    # เพราะหน้า index ของแอป fetch('/api/...') และเปิด /player_path/... /hls/... โดยเริ่มด้วย /
    # จึงต้องผูก path เหล่านี้ด้วย เพื่อให้ทำงานแม้อยู่ใต้ /video-streaming/
    ProxyPass        /api/         http://127.0.0.1:5000/api/         retry=0
    ProxyPassReverse /api/         http://127.0.0.1:5000/api/
    ProxyPass        /player_path/ http://127.0.0.1:5000/player_path/ retry=0
    ProxyPassReverse /player_path/ http://127.0.0.1:5000/player_path/
    ProxyPass        /hls/         http://127.0.0.1:5000/hls/         retry=0
    ProxyPassReverse /hls/         http://127.0.0.1:5000/hls/
    ProxyPass        /hlsplayer/   http://127.0.0.1:5000/hlsplayer/   retry=0
    ProxyPassReverse /hlsplayer/   http://127.0.0.1:5000/hlsplayer/

    # อนุญาตเมธอดที่จำเป็น และเปิดสิทธิ์
    <Location /video-streaming/>
        <LimitExcept GET HEAD OPTIONS>
            Require all denied
        </LimitExcept>
        Require all granted
    </Location>
    <Location /api/>
        <LimitExcept GET HEAD OPTIONS>
            Require all denied
        </LimitExcept>
        Require all granted
    </Location>
    <Location /player_path/>
        Require all granted
    </Location>
    <Location /hls/>
        Require all granted
    </Location>
    <Location /hlsplayer/>
        Require all granted
    </Location>
    # =========================================================================== 
```

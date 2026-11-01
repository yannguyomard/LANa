@echo off
rem Lance LANa sous Windows (Python 3.9 ou plus récent requis : https://www.python.org/downloads/)
cd /d "%~dp0"
where py >nul 2>nul && (py -3 run.py %* & goto :eof)
python run.py %*

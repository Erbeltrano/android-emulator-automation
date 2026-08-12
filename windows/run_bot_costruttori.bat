@echo off
cd /d C:\Users\simon
call cred.bat

echo Avvio BlueStacks...
start "" "C:\Program Files\BlueStacks_nxt\HD-Player.exe"

echo Aspetto che ADB veda il device...
set ADB="C:\Program Files\BlueStacks_nxt\HD-Adb.exe"
set /a tries=0
:waitadb
%ADB% devices | findstr /C:"device" | findstr /V "List" >nul
if not errorlevel 1 goto adbready
set /a tries+=1
if %tries% GEQ 30 goto adbready
timeout /t 3 /nobreak >nul
goto waitadb
:adbready

echo Avvio Clash of Clans...
%ADB% shell monkey -p com.supercell.clashofclans -c android.intent.category.LAUNCHER 1
echo Aspetto che il gioco carichi...
rem Ridotto da 35 a 25s il 2026-08-12 (richiesta utente: velocizzare l'avvio):
rem il bot stesso, subito dopo, aspetta fino a 15s in piu' che il villaggio
rem sia pronto prima di scoutare/attaccare (rete di sicurezza gia' esistente).
rem NON ridurre oltre senza verificarlo dal vivo: il dezoom subito dopo tocca
rem davvero la camera del gioco, e uno zoom sbagliato per un caricamento
rem ancora in corso e' stato causa di piu' bug seri in passato (vedi recap.md).
timeout /t 25 /nobreak >nul

echo Dezoom automatico della camera...
powershell -ExecutionPolicy Bypass -File "C:\Users\simon\dezoom_camera.ps1"

echo Avvio il bot Villaggio Costruttori...
"C:\Users\simon\AppData\Local\Programs\Python\Python312\python.exe" -u bot_costruttori.py --cycles 0 > bot_costruttori_log.txt 2>&1

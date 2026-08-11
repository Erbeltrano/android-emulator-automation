# Dezoom automatico della camera BlueStacks/Clash of Clans, eseguito dentro
# run_bot.bat / run_bot_costruttori.bat (Task Scheduler, LogonType=Interactive)
# subito dopo che il gioco ha caricato.
#
# Perche' serve: la posizione/zoom della camera in-game vive solo nello stato
# live del processo BlueStacks (nessun file la persiste su disco, verificato
# il 2026-08-07 cercando senza successo un salvataggio in shared_prefs con
# root abilitato) - si perde ogni volta che BlueStacks riparte da zero (es.
# il PC Windows viene spento per inattivita' e risvegliato via Wake-on-LAN).
# Senza lo zoom giusto DEPLOY_POINTS/OCR non sono piu' calibrati e gli
# attacchi schierano male.
#
# Perche' un tasto sintetico via ADB o via SSH (keybd_event/mouse_event
# lanciati da una sessione SSH) non funziona: sessioni diverse girano in
# "window station" isolate dalla sessione desktop interattiva reale, l'input
# sintetico non la raggiunge mai (confermato piu' volte, vedi recap.md). Uno
# script lanciato da un Task Scheduler con LogonType=Interactive gira invece
# DENTRO la sessione desktop vera: da li' SendInput/mouse_event funzionano
# davvero (confermato dal vivo il 2026-08-07, l'utente ha visto la camera
# zoommare da sola guardando lo schermo fisico).
#
# Simula lo stesso identico gesto che l'utente fa a mano: tasto destro del
# mouse tenuto premuto ~2.5s al centro della finestra di BlueStacks (stessa
# durata, "tasto destro tenuto 2s", confermata funzionante dall'utente in
# sessioni precedenti). Sicuro da rilanciare anche se lo zoom e' gia'
# corretto: il gesto porta la camera al livello di zoom minimo, non lo
# alterna (tenerlo premuto quando si e' gia' al minimo non ha effetto).
#
# IMPORTANTE - timing: se lanciato mentre Clash of Clans non ha ancora
# finito la transizione dalla schermata di caricamento al villaggio, il
# click destro viene interpretato come tasto "Indietro" invece che come
# gesto di zoom, e il gioco si chiude tornando alla schermata Store di
# BlueStacks (visto dal vivo il 2026-08-07: 20s di attesa dopo il lancio
# di CoC non bastavano su un riavvio vero, bastavano invece quando CoC era
# gia' stabile da un po'). Per questo run_bot.bat/run_bot_costruttori.bat
# aspettano 35s (non 20s) prima di chiamare questo script - non ridurre
# senza aver verificato dal vivo che il villaggio sia gia' visibile a quel
# punto.

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32Dezoom {
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, int dx, int dy, uint dwData, UIntPtr dwExtraInfo);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
  public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
}
"@

$logFile = "C:\Users\simon\dezoom_log.txt"
"[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Avvio dezoom_camera.ps1" | Out-File -FilePath $logFile

$proc = Get-Process -Name HD-Player -ErrorAction SilentlyContinue
if (-not $proc -or $proc.MainWindowHandle -eq 0) {
    "Finestra BlueStacks non trovata, salto il dezoom." | Out-File -FilePath $logFile -Append
    exit 0
}

$rect = New-Object Win32Dezoom+RECT
[Win32Dezoom]::GetWindowRect($proc.MainWindowHandle, [ref]$rect) | Out-Null
[Win32Dezoom]::SetForegroundWindow($proc.MainWindowHandle) | Out-Null
Start-Sleep -Milliseconds 500

$cx = [int](($rect.Left + $rect.Right) / 2)
$cy = [int](($rect.Top + $rect.Bottom) / 2)
"Click destro tenuto al centro finestra: $cx,$cy (rect $($rect.Left),$($rect.Top),$($rect.Right),$($rect.Bottom))" | Out-File -FilePath $logFile -Append

[Win32Dezoom]::SetCursorPos($cx, $cy) | Out-Null
Start-Sleep -Milliseconds 200
[Win32Dezoom]::mouse_event(0x0008, 0, 0, 0, [UIntPtr]::Zero)   # MOUSEEVENTF_RIGHTDOWN
Start-Sleep -Milliseconds 2500
[Win32Dezoom]::mouse_event(0x0010, 0, 0, 0, [UIntPtr]::Zero)   # MOUSEEVENTF_RIGHTUP

"Dezoom completato." | Out-File -FilePath $logFile -Append

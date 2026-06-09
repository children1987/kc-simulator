@echo off
echo ============================================
echo   KC Simulator - Charge Battery to 100%%
echo ============================================
echo.
powershell -Command "$r=Invoke-WebRequest 'http://127.0.0.1:8080/api/charge' -Method POST -UseBasicParsing; $d=$r.Content|ConvertFrom-Json; if($d.ok){Write-Host '[OK] Battery: 100%%' -ForegroundColor Green}else{Write-Host '[FAIL]' -ForegroundColor Red}"
echo.
pause

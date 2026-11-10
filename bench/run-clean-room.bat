@echo off
"C:\Program Files\Git\bin\bash.exe" /d/TCAD_Mesh/scripts/clean-room-test.sh > D:\TCAD_Mesh\bench\clean-room-output.txt 2>&1
echo ExitCode:%ERRORLEVEL% >> D:\TCAD_Mesh\bench\clean-room-output.txt

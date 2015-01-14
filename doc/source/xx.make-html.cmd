call xx.make clean
del /f /s /q autosummary\*
call xx.make html
echo about to copy to
FOR /F %%i IN ("..\..\..\puq gh-pages") DO echo %%~fi\puq gh pages
pause
::try to copy the html to gh-pages folder
xcopy "_build\html" "..\..\..\puq gh-pages" /Y /E /R /Q
::rd /s /q _build
pause
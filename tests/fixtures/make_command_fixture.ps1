# Erzeugt tests/fixtures/command_safeword.wav per Windows-SAPI-TTS (offline).
# Bauplan-Beispiel fuer den Safe-Word-Befehl (M5) mit dem aktuellen Trigger "Kimono"
# (ASR-getestet; "Redax" wurde von Whisper nicht zuverlaessig gehoert).
# Aufruf:  pwsh tests/fixtures/make_command_fixture.ps1
Add-Type -AssemblyName System.Speech

$text = "Der Umsatz stieg um 20 Prozent. Kimono, mach den letzten Satz formeller."
$out = Join-Path $PSScriptRoot "command_safeword.wav"

$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$german = $synth.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -eq "de-DE" } | Select-Object -First 1
if (-not $german) { Write-Error "Keine deutsche TTS-Stimme installiert."; exit 1 }
$synth.SelectVoice($german.VoiceInfo.Name)

$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$synth.SetOutputToWaveFile($out, $format)
$synth.Speak($text)
$synth.Dispose()
Write-Host "Geschrieben: $out"

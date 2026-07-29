# Erzeugt tests/fixtures/diktat_de.wav per Windows-SAPI-TTS (offline, keine API).
# Aufruf:  pwsh tests/fixtures/make_fixture.ps1
Add-Type -AssemblyName System.Speech

$text = "Ich wollte nur sagen, dass das Projekt ziemlich gut läuft und wir im Zeitplan sind."
$out = Join-Path $PSScriptRoot "diktat_de.wav"

$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$german = $synth.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -eq "de-DE" } | Select-Object -First 1
if (-not $german) { Write-Error "Keine deutsche TTS-Stimme installiert."; exit 1 }
$synth.SelectVoice($german.VoiceInfo.Name)

$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$synth.SetOutputToWaveFile($out, $format)
$synth.Speak($text)
$synth.Dispose()
Write-Host "Geschrieben: $out"

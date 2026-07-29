# Erzeugt gesprochene Mathe-Saetze als WAVs fuer den M6-Test (Windows-SAPI, offline).
# Aufruf:  pwsh tests/fixtures/make_math_fixtures.ps1
Add-Type -AssemblyName System.Speech

$cases = @(
    @{ name = "math_quadratisch";  text = "x Quadrat plus b x plus c gleich null" },
    @{ name = "math_summe";        text = "die Summe von i gleich 1 bis n von i Quadrat" },
    @{ name = "math_integral";     text = "Integral von null bis unendlich von e hoch minus x Quadrat d x" },
    @{ name = "math_wurzel";       text = "Wurzel aus a Quadrat plus b Quadrat" },
    @{ name = "math_klammern";     text = "in Klammern a plus b Klammer zu hoch zwei" },
    @{ name = "math_prosodie";     text = "x hoch zwei plus eins, das Ganze durch zwei" },
    @{ name = "math_delimiter";    text = "Formel: minus b plus minus Wurzel aus b Quadrat minus vier a c, das Ganze durch zwei a, Formel Ende" }
)

$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$german = $synth.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -eq "de-DE" } | Select-Object -First 1
if (-not $german) { Write-Error "Keine deutsche TTS-Stimme installiert."; exit 1 }
$synth.SelectVoice($german.VoiceInfo.Name)
$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)

foreach ($c in $cases) {
    $out = Join-Path $PSScriptRoot "$($c.name).wav"
    $synth.SetOutputToWaveFile($out, $format)
    $synth.Speak($c.text)
    Write-Host "Geschrieben: $out"
}
$synth.Dispose()

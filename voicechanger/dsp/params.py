"""Ses ayarları: DSP, arayüz ve presetlerin ortak dili.

Bu dosya yalnızca veri tanımlar (dosya okuma/yazma yok). Slider aralıkları
da burada tanımlıdır; arayüz sliderları bu listeden otomatik üretir.
"""

from dataclasses import asdict, dataclass, fields

PITCH_MODE_SEMITONES = "semitones"  # sabit kaydırma: "+10 yarım ton"
PITCH_MODE_TARGET = "target"        # hedef perde: "ortalama perdem 230 Hz olsun"


@dataclass
class VoiceSettings:
    # Perde
    pitch_mode: str = PITCH_MODE_SEMITONES
    pitch_semitones: float = 10.0
    target_f0_hz: float = 220.0
    intonation: float = 1.0          # 1 = aynen, >1 = daha canlı tonlama
    smoothness: float = 0.0          # 0..1, perde titremesini (jitter) yumuşatma
    # Tını
    formant_ratio: float = 1.17
    lowcut_hz: float = 80.0          # alt gövde kesimi
    chest_db: float = 0.0            # 300 Hz civarı göğüs rezonansı
    softness: float = 0.0            # 0..1, sert üst harmonikleri kısma
    air_db: float = 0.0              # 8 kHz üstü hava/parlaklık
    breathiness: float = 0.0         # 0..1, nefes gürültüsü
    tremor: float = 0.0              # 0..1, yaşlı sesteki titreme (perde + şiddet, ~5.5 Hz)
    # Teknik
    gate_threshold_db: float = -45.0
    auto_level: bool = True          # konuşma seviyesini otomatik olarak hedefe çek
    output_gain_db: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict, base: "VoiceSettings | None" = None) -> "VoiceSettings":
        """Bilinmeyen anahtarları yok say; eksikleri base'den (yoksa varsayılandan) doldur."""
        known = {f.name for f in fields(cls)}
        merged = (base or cls()).to_dict()
        merged.update({k: v for k, v in data.items() if k in known})
        return cls(**merged)

    def processor_params(self) -> dict:
        """Ses değiştirici (PSOLA / ileride AI) parametreleri."""
        return {
            "pitch_mode": self.pitch_mode,
            "pitch_semitones": self.pitch_semitones,
            "target_f0_hz": self.target_f0_hz,
            "intonation": self.intonation,
            "smoothness": self.smoothness,
            "formant_ratio": self.formant_ratio,
            "tremor": self.tremor,
        }


@dataclass(frozen=True)
class SliderSpec:
    field: str
    label: str
    minimum: float
    maximum: float
    step: float
    fmt: str
    group: str
    hint: str = ""
    display_scale: float = 1.0  # gösterimde çarpan (0..1 → %0..100)

    def format(self, value: float) -> str:
        return self.fmt.format(value * self.display_scale)


PERCENT = "%{:.0f}"

SLIDERS = [
    SliderSpec("pitch_semitones", "Perde kaydırma", -12, 16, 0.5, "{:+.1f} yarım ton", "Perde",
               "Sesin ne kadar inceleşeceği. Kadın sesi için +9…+12."),
    SliderSpec("target_f0_hz", "Hedef perde", 80, 320, 5, "{:.0f} Hz", "Perde",
               "Çıkış sesinin ortalama perdesi. Genç kadın 200–250, yaşlı kadın 170–195, "
               "erkek 100–140, derin erkek 85–100 Hz."),
    SliderSpec("intonation", "Tonlama canlılığı", 0.6, 1.8, 0.05, "×{:.2f}", "Perde",
               "Perdenin iniş çıkışlarını büyütür. 1.0 = olduğu gibi. Kadın: 1.15–1.35."),
    SliderSpec("smoothness", "Akıcılık", 0, 1, 0.05, PERCENT, "Perde",
               "Perde titremesini ve hırıltıyı yumuşatır; ses akıcı ve pürüzsüz olur. Öneri: %40–70.", 100),
    SliderSpec("formant_ratio", "Formant (ses yolu)", 0.9, 1.5, 0.01, "×{:.2f}", "Tını",
               "Tınının temeli. Kadın: 1.15–1.21. 1.23 üstü çocuksu/anime duyulur."),
    SliderSpec("lowcut_hz", "İncelik (alt kesim)", 60, 250, 5, "{:.0f} Hz", "Tını",
               "Erkeksi gövdeyi ve altta kalan erkek perdesini keser. Öneri: 130–160 Hz."),
    SliderSpec("chest_db", "Göğüs rezonansı", -12, 6, 0.5, "{:+.1f} dB", "Tını",
               "Kısmak sesi inceltir, tok tınıyı azaltır. Öneri: -2…-5 dB."),
    SliderSpec("softness", "Yumuşaklık", 0, 1, 0.05, PERCENT, "Tını",
               "Sert, vızıltılı üst harmonikleri ve hışırtıyı kısar. Öneri: %30–60.", 100),
    SliderSpec("air_db", "Hava / parlaklık", -6, 9, 0.5, "{:+.1f} dB", "Tını",
               "En tepe frekansları açar: daha parlak ve havadar. Öneri: 0…+2 dB; fazlası hışırtıyı da açar."),
    SliderSpec("breathiness", "Nefes", 0, 1, 0.05, PERCENT, "Tını",
               "Sese yumuşak bir nefes katar. Öneri: %5–20; fazlası hışırtı/fısıltı yapar.", 100),
    SliderSpec("tremor", "Titreme (yaşlı ses)", 0, 1, 0.05, PERCENT, "Tını",
               "Yaşlı seslerdeki hafif titreme: perde ve şiddet saniyede ~5–6 kez dalgalanır. "
               "Yaşlı karakter: %30–60; 0 = kapalı.", 100),
    SliderSpec("gate_threshold_db", "Gürültü kapısı eşiği", -80, -20, 1, "{:.0f} dBFS", "Teknik",
               "Bu seviyenin altındaki ses (nefes, klavye) kesilir."),
    SliderSpec("output_gain_db", "Çıkış seviyesi", -12, 12, 0.5, "{:+.1f} dB", "Teknik",
               "Otomatik seviye açıksa ince ayardır (0 önerilir); kapalıysa sesin genel seviyesi."),
]


@dataclass(frozen=True)
class ToggleSpec:
    field: str
    label: str
    group: str
    hint: str = ""


TOGGLES = [
    ToggleSpec("auto_level", "Otomatik ses seviyesi", "Teknik",
               "Mikrofonun kısık da olsa sesi Discord için ideal seviyeye çeker; tınıya dokunmaz. "
               "Sessizlikte gürültüyü şişirmez, ani bağırmada patlatmaz. Açık önerilir."),
]


def migrate_settings(stored: dict) -> dict:
    """Eski sürümlerde kaydedilmiş ayarları güncelle (kopya döndürür).

    Otomatik seviye ilk kez geldiğinde: eski 'Çıkış seviyesi' büyük ihtimalle
    kısık mikrofonu telafi etmek için yükseltilmişti; otomatik seviyenin üstüne
    binip sesi patlatmasın diye 0'a çekilir.
    """
    data = dict(stored)
    if "auto_level" not in data:
        data["auto_level"] = True
        data["output_gain_db"] = 0.0
    return data

# Sınırların ötesinde ses çocuksu/anime karakterine kayar (arayüz uyarısı için)
CHILDLIKE_FORMANT = 1.23
CHILDLIKE_TARGET_HZ = 265.0

BUILTIN_PRESETS = {
    "Varsayılan kadın": VoiceSettings(),
    "Hafif yetişkin": VoiceSettings(
        pitch_mode=PITCH_MODE_TARGET, target_f0_hz=235.0, intonation=1.25, smoothness=0.55,
        formant_ratio=1.20, lowcut_hz=150.0, chest_db=-3.0, softness=0.45, air_db=1.0,
        breathiness=0.1,
    ),
    # Olgun kadın (40-55): genç kadından biraz pes, daha tok, sakin tonlama
    "Olgun kadın": VoiceSettings(
        pitch_mode=PITCH_MODE_TARGET, target_f0_hz=200.0, intonation=1.15, smoothness=0.45,
        formant_ratio=1.14, lowcut_hz=110.0, chest_db=-1.0, softness=0.40, air_db=0.0,
        breathiness=0.10,
    ),
    # Yaşlı kadın: daha pes perde, pürüz (akıcılık düşük), nefes ve titreme
    "Yaşlı kadın": VoiceSettings(
        pitch_mode=PITCH_MODE_TARGET, target_f0_hz=185.0, intonation=1.15, smoothness=0.15,
        formant_ratio=1.12, lowcut_hz=110.0, chest_db=-1.5, softness=0.35, air_db=-1.0,
        breathiness=0.30, tremor=0.45,
    ),
    # Yaşlı adam: erkek perdesi, hafif ince tını (yaşla formant yükselir), pürüz, nefes, titreme
    "Yaşlı adam": VoiceSettings(
        pitch_mode=PITCH_MODE_TARGET, target_f0_hz=120.0, intonation=1.0, smoothness=0.10,
        formant_ratio=0.98, lowcut_hz=70.0, chest_db=0.0, softness=0.30, air_db=-2.0,
        breathiness=0.25, tremor=0.50,
    ),
    # Derin erkek (anlatıcı/kötü adam): pes perde, uzun ses yolu, göğüs rezonansı
    "Derin erkek": VoiceSettings(
        pitch_mode=PITCH_MODE_TARGET, target_f0_hz=95.0, intonation=0.9, smoothness=0.40,
        formant_ratio=0.92, lowcut_hz=60.0, chest_db=3.0, softness=0.30, air_db=-1.0,
        breathiness=0.0,
    ),
}

# Hazır presetlerin eski sürümleri (dosyaya yazıldığı haliyle). Kayıtlı bir
# preset bunlardan biriyle birebir aynıysa kullanıcı değiştirmemiş demektir;
# güncel değerlerle değiştirilir. Kullanıcının değiştirdiği presetlere dokunulmaz.
_HAFIF_V1 = {"pitch_mode": "target", "pitch_semitones": 10.0, "target_f0_hz": 235.0,
             "intonation": 1.25, "formant_ratio": 1.2, "chest_db": -3.0, "air_db": 3.0,
             "gate_threshold_db": -45.0, "output_gain_db": 0.0}
_HAFIF_V2 = {**_HAFIF_V1, "smoothness": 0.55, "lowcut_hz": 150.0, "softness": 0.3, "breathiness": 0.25}
OUTDATED_BUILTIN_PRESETS = {"Hafif yetişkin": [_HAFIF_V1, _HAFIF_V2]}


def is_outdated_builtin(name: str, stored: dict) -> bool:
    return any(stored == old for old in OUTDATED_BUILTIN_PRESETS.get(name, []))

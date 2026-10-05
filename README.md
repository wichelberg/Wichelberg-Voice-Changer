# Wichelberg Voice Changer

Windows için gerçek zamanlı ses değiştirici. Sesini seçilen hedef sese çevirir ve VB-Cable üzerinden
Discord ve FiveM'e aktarır.

- **DSP modu** (hazır): PSOLA + formant kaydırma. CPU yükü ~%0.5, uçtan uca gecikme ~60–70 ms.
- **AI modu** (bkz. bölüm 9): RVC v2 ses modelleri, sadece ONNX Runtime ile. PyTorch/CUDA yoktur.
  Her şey CPU'da çalışır; GPU (DirectML) isteğe bağlıdır ve varsayılan olarak kapalıdır.

> **Gerçek kişilerin sesleri sadece kendi rızalarıyla eklenebilir.** İzinsiz ünlü, yayıncı veya tanıdık sesi
> klonlamak ve kullanmak yasaktır. Her ses paketinde lisans ve kaynak bilgisi zorunludur.

---

## 1. Kurulum

### VB-Cable (bir kez)
1. https://vb-audio.com/Cable/ adresinden **VBCABLE_Driver_Pack** dosyasını indir ve zip'ten çıkar.
2. `VBCABLE_Setup_x64.exe` → sağ tık → **Yönetici olarak çalıştır** → *Install Driver*.
3. **Bilgisayarı yeniden başlat.**
4. Windows Ses Ayarları'nda iki yeni cihaz görünür: **CABLE Input** (çıkış) ve **CABLE Output** (giriş).

> Not: Windows'un varsayılan çıkışını CABLE Input yapma; yoksa bilgisayarın tüm sesi Discord'a gider.

### Program
- **Kullanıcılar:** release zip'ini indir, çıkar, `Wichelberg.exe`'ye çift tıkla. İlk açılışta kurulum ekranı
  Python'u, paketleri ve ortak AI modellerini sadece program klasörüne indirir (Python kurulu olması gerekmez).
  Ayrıntılar release reposundaki README'de (`launcher/RELEASE_README.md`).
- **Geliştirme:** `start.bat`'a çift tıkla. Proje klasöründe `.venv` oluşturulur ve paketler **sadece oraya**
  kurulur (global Python'a dokunulmaz). Python 3.11 gerekir (`py -3.11`).

---

## 2. Kullanım

Program iki görünümle açılır (sağ üstteki **Gelişmiş görünüm** anahtarı; yanında açık/koyu tema düğmesi):
- **Basit:** Ana ekran (durum, Başlat, mod ve ses seçimi, cihazlar, seviye) + Ses Kütüphanesi.
- **Gelişmiş:** + soldaki DSP ses ayarları, Ses stüdyosu, gecikme/CPU ölçümleri, AI ayarları (GPU, perde düzeltme,
  tını sadakati), kısayol ve otomatik başlatma.

### Ses Kütüphanesi sekmesi
- Program içinde ses gelmez. Sana gönderilen ses dosyasını (`.zip`) listeye **sürükle** veya **İçe aktar…**'a bas.
  Program paketi açmadan önce adını, hazırlayanı, lisansı ve kaynağı gösterir; lisansı/kaynağı boş veya dosyası
  bozuk (sha256 tutmayan) paket kurulmaz. Aynı ses tekrar gelirse yenisiyle değiştirir; ses ayarların korunur.
- **▶ Önizle** sesin örneğini dinletir, **Sil** sesi kaldırır.
- **Ortak AI modelleri:** her AI sesinin kullandığı genel modeller (bir kez iner).
- **Hız testi:** AI modunu ilk kullanmadan önce bir kez çalıştır (~5 dk, oyun ve canlı kapalıyken). AI modunun bu
  bilgisayarda oyunla birlikte çalışıp çalışmadığını ölçer ve ayarları seçer.

### Ana ekran
1. **Mikrofon:** kendi mikrofonun. *NVIDIA Broadcast* mikrofonunu seçme; GPU kullanır.
2. **Discord'a çıkış:** `CABLE Input (VB-Audio Virtual Cable)`.
3. İstersen **Kendimi duy** kutusunu işaretleyip kulaklığını seç. Hoparlör seçme; mikrofon sesi geri alır ve çınlama olur.
4. **▶ Başlat**.
5. **Ctrl+F7** ile dönüştürmeyi açıp kapatırsın. Kapalıyken normal sesin gider. "Kendimi duy" açıksa her geçişte kulaklıkta kısa bir bip duyarsın (Discord duymaz). Kısayol arayüzden değiştirilebilir. Programı kapatan bir kısayol bilinçli olarak yoktur; kapatmak için pencereyi kapat.

**Ses** kartında mod seçilir: **AI** (seçili AI sesi), **DSP** (hafif, preset ile) veya **Normal ses**.
VB-Cable kurulu değilse ana ekran indirme bağlantısını ve kurulum adımlarını gösterir.

Soldaki ses ayarları (Gelişmiş görünüm) **canlıyken anında** etki eder.

### Ses stüdyosu sekmesi (Gelişmiş görünüm)
Kayıt al (10 sn), ayarları kayıt üzerinde dene, orijinal/dönüştürülmüş sesi karşılaştır.
Slider'ı bıraktığında ses otomatik dönüştürülür ve çalınır. Canlı açıkken stüdyo kapalıdır (takılma olmasın diye).

### Ses ayarları
| Grup | Slider | Ne yapar |
|---|---|---|
| Perde | Perde kaydırma / Hedef perde | Sesin tizliği. "Hedef perde" modunda çıkış ortalaması verilen Hz'de kalır |
| | Tonlama canlılığı | Perdenin iniş çıkışlarını büyütür |
| | Akıcılık | Perde titremesini ve hırıltıyı yumuşatır |
| Tını | Formant | Tınının temeli (ses yolu uzunluğu). Kadın: 1.15–1.21 |
| | İncelik (alt kesim) | Erkeksi gövdeyi ve altta kalan erkek perdesini keser |
| | Göğüs rezonansı | Tok tınıyı azaltır |
| | Yumuşaklık | Sert üst harmonikleri ve hışırtıyı kısar |
| | Hava / parlaklık | Tizleri açar (fazlası hışırtıyı da açar) |
| | Nefes | Sese nefes katar (fazlası hışırtı yapar) |
| | Titreme (yaşlı ses) | Perde ve şiddet saniyede ~5–6 kez dalgalanır; yaşlı karakterler için %30–60 |
| Teknik | Gürültü kapısı | Bu seviyenin altı (nefes, klavye) Discord'a gitmez |
| | Çıkış seviyesi | Genel ses seviyesi |

Preset'ler: **Kaydet…** ile kendi ayarını kaydet. Hazır preset'ler: *Varsayılan kadın*, *Hafif yetişkin*,
*Olgun kadın*, *Yaşlı kadın*, *Yaşlı adam*, *Derin erkek* (DSP modunda geçerlidir; AI modunda ses, seçilen
AI sesinden gelir).
Formant 1.23'ün veya hedef perde 265 Hz'in üstü çocuksu/anime tınısına kayar; arayüz uyarır.

---

## 3. Discord ayarları
**Kullanıcı Ayarları → Ses ve Görüntü**
- **Giriş Aygıtı:** `CABLE Output (VB-Audio Virtual Cable)`
- **Gürültü Azaltma (Krisp):** Kapalı. Dönüştürülmüş sesi bozar; gürültü kapısı bu işi zaten yapıyor.
- **Yankı Engelleme:** Kapalı
- **Otomatik Kazanç Kontrolü:** Kapalı
- **Giriş Hassasiyeti:** Otomatik açık kalabilir. Ses kesik geliyorsa kapatıp çubuğu sola çek.
- Test: Ayarlar'daki **"Haydi Kontrol Edelim"** ile kendini dinle.

## 4. FiveM ayarları
**Ayarlar → Ses Sohbeti (Voice Chat)**
- **Giriş Cihazı / Mikrofon:** `CABLE Output (VB-Audio Virtual Cable)`
- Listede yoksa: Windows **Ses Ayarları → Giriş** bölümünde varsayılan kayıt cihazını **CABLE Output** yap ve FiveM'i yeniden başlat.
- Oyun **yönetici olarak** çalışıyorsa, Ctrl+F7'nin oyun içinde çalışması için bu programı da yönetici olarak aç.

---

## 5. Ölçümler (Ryzen AI 7 350, laptop mikrofonu)
| | Değer |
|---|---|
| Algoritma gecikmesi | 27 ms |
| Uçtan uca (düşük gecikme modu) | ~60–70 ms (+ VB-Cable) |
| Uçtan uca (paylaşımlı mod) | ~85–95 ms (+ VB-Cable) |
| CPU (programın tamamı) | toplamın ~%0.4–0.7'si |
| Ses işleme | 10 ms'lik bloğun ~%3'ü |
| Takılma | 20 sn testte 0 |

**Düşük gecikme modu** yalnızca çıkış CABLE Input olduğunda devreye girer ve **sadece mikrofonu** WASAPI özel
modunda açar (~12 ms kazanç). Bu sırada başka uygulamalar mikrofonu doğrudan kullanamaz; Discord ve FiveM CABLE
Output'u kullandığı için etkilenmez. Çıkış başka bir cihazsa (ör. kulaklıkla test) her şey paylaşımlı modda açılır.
Özel mod açılamazsa program kendiliğinden paylaşımlı moda geçer.

**CABLE Input her zaman paylaşımlı modda açılır.** VB-Cable özel modda sesi parçalıyor. CABLE Output'tan geri kayıt
ile ölçüldü: özel modda 8 saniyede ~200 kesilme, paylaşımlı modda 20 saniyede 0 kesilme.

VB-Cable gecikmesini düşürmek için: `VBCABLE_ControlPanel.exe` → *Options* → **Max Latency** değerini düşür (ör. 2048 smp)
ve iç örnekleme hızını **48000 Hz** yap.

---

## 6. Güvenlik
- İşleme hatası veya takılma olursa CABLE'a **sessizlik** gider, asla ham ses gitmez.
- Program kapanırsa veya çökerse ses akışı da kapanır; Discord'a sessizlik gider.
- Dönüştürme **kapalıyken (Ctrl+F7)** normal sesin gider. Bu bilinçli bir tercih.

---

## 7. Sorun giderme
| Sorun | Çözüm |
|---|---|
| Discord'da ses yok | Ana ekranda durum yeşil mi (● CANLI)? Discord giriş aygıtı **CABLE Output** mu? |
| "VB-Cable bulunamadı" | Kurulumdan sonra bilgisayarı yeniden başlat, sonra **Cihazları yenile** |
| Hışırtı | **Nefes**'i azalt, **Yumuşaklık**'ı artır, **Hava**'yı 0–1 dB yap |
| Robotik veya pürüzlü ses | **Akıcılık**'ı artır, formantı 1.20'nin altına çek |
| Çınlama / yankı | "Kendimi duy" hoparlöre gidiyor; kulaklık seç |
| Ses kesik kesik | **Gürültü kapısı** eşiğini düşür (ör. -55) |
| Takılma sayacı artıyor | Arka planda ağır programları kapat; olmazsa düşük gecikme modunu kapat |
| Kısayol oyunda çalışmıyor | Programı yönetici olarak çalıştır |
| Mikrofon başka uygulamada çalışmıyor | Canlıyı durdur veya düşük gecikme modunu kapat |

---

## 8. Geliştirici notları

### Klasör yapısı
```
start.bat, setup.bat, requirements.txt, README.md   (geliştirme)
launcher/          Wichelberg.exe başlatıcısı: kurulum.py (kurulum mantığı), wichelberg.py (kurulum ekranı),
                   build_release.py (release zip'i), RELEASE_README.md (release reposunun README'si)
config/            config.json (son ayarlar, cihazlar, kısayol) + presets/      (repoya girmez)
data/recordings/   test kayıtları        data/outputs/  dönüştürülmüş dosyalar    (repoya girmez)
models/shared/     ortak AI modelleri    models/voices/<id>/  ses paketleri     (repoya girmez)
docs/              DECISIONS.md (tüm kararlar)
tests/             unittest testleri
voicechanger/
  ai/              AI katmanı (ONNX Runtime) + library.py (Ses Kütüphanesi: zip içe aktarma)
  dsp/             ses işleme (cihaz/arayüzden bağımsız)
    base.py        VoiceProcessor arayüzü
    psola.py       PSOLA perde + formant kaydırıcı
    pitch_detect.py YIN perde tespiti
    gate.py, tone.py, breath.py, chain.py, params.py, world_offline.py
  engine.py        gerçek zamanlı motor (WASAPI, ring buffer, CABLE + monitör)
  hotkeys.py       global kısayol
  gui/             tkinter + sv-ttk arayüzü (app, live_panel, ai_controls, library_panel, voice_panel,
                   studio_panel, theme, widgets)
  render.py, recorder.py, settings.py, paths.py, wavio.py
  tools/           komut satırı: record, convert, setup_models, benchmark
```

### Yöntem
- **Perde:** TD-PSOLA. YIN ile periyot bulunur (histerezisli), periyot işaretleri korelasyonla hizalanır, grain'ler
  yeni aralıkla üst üste eklenir. Komşu grain'ler karıştırılır; böylece büyük kaydırmalarda "hayalet" titreşim olmaz.
- **Formant:** Her grain yeniden örneklenir; spektral zarf perdeden bağımsız olarak kayar.
- **Tıkırtısızlık:** Hann pencereli overlap-add, durumlu filtreler, 20 ms crossfade ile bypass.
- WORLD (pyworld) yalnızca stüdyoda karşılaştırma için var. Gerçek zamanlıda CPU'yu ~10 kat fazla kullanır.

### Kütüphaneler ve lisanslar
| Paket | Lisans | Neden |
|---|---|---|
| numpy | BSD-3 | DSP hesapları |
| scipy | BSD-3 | durumlu filtreler, FFT, yeniden örnekleme |
| sounddevice | MIT | PortAudio/WASAPI ile düşük gecikmeli ses giriş/çıkışı |
| soundfile | BSD-3 | WAV okuma/yazma |
| psutil | BSD-3 | CPU göstergesi |
| pynput | LGPL-3.0 | oyun içindeyken de çalışan global kısayol |
| pyworld | MIT | yalnızca offline WORLD karşılaştırması |
| onnxruntime-directml | MIT (içindeki DirectML.dll: Microsoft'un ücretsiz yeniden dağıtım lisansı) | AI çıkarımı, CPU + isteğe bağlı GPU |
| faiss-cpu | MIT | ses modelinin index'inde arama |
| tkinterdnd2 | MIT | Ses Kütüphanesi'ne sürükle-bırak (yoksa "İçe aktar…" çalışır) |
| sv-ttk | MIT | modern arayüz teması (açık/koyu) |

### AI modelleri ve lisansları
| Model | Lisans | Kaynak |
|---|---|---|
| ContentVec (`contentvec.onnx`) | MIT | auspicious3000/contentvec, HF `lengyue233/content-vec-best` |
| FCPE (`fcpe.onnx`, varsayılan perde) | MIT | CNChTu/FCPE, `torchfcpe` paketi |
| RMVPE (`rmvpe.onnx`, isteğe bağlı) | Kod Apache-2.0; ağırlık MIT + **"yalnızca araştırma"** notu | HF `lj1995/VoiceConversionWebUI` |
| RVC v2 mimarisi (dışa aktarma kodu) | MIT | RVC-Project/Retrieval-based-Voice-Conversion-WebUI |
| Ana kadın sesi (`ana_kadin`) | Veri VCTK CC BY 4.0 + RVC ağırlıkları ("yalnızca araştırma" notu) | RVC pretrained_v2, VCTK konuşmacı 70. **Atıf: VCTK Corpus, CSTR, University of Edinburgh.** Sadece özel grup içinde |

Ses paketlerinin her birinin kendi lisansı `voice.json` içindedir; lisansı veya kaynağı boş olan ses yüklenmez.

### AI katmanı
`voicechanger/ai/`: `runtime.py` (CPU/GPU seçimi tek yerde, GPU hatasında CPU'ya dönüş), `voices.py` (ses paketi
doğrulama), `rvc_onnx.py` (RVC çıkarımı, akış), `parity.py` (CPU-GPU eşitlik ölçümü). ONNX dosyaları ayrı
eğitim reposundaki `training/export_onnx.py` ile üretilir (torch gerektirir; bu repoda yok). Kararlar:
`docs/DECISIONS.md`.

### Komut satırı
```
.venv\Scripts\python -m voicechanger.tools.record --list
.venv\Scripts\python -m voicechanger.tools.record --seconds 10
.venv\Scripts\python -m voicechanger.tools.convert --preset "Hafif yetişkin" --world
.venv\Scripts\python -m voicechanger.tools.setup_models      ortak AI modellerini kur/doğrula
.venv\Scripts\python -m voicechanger.tools.benchmark         AI hız testi (sonuç config.json'a)
.venv\Scripts\python -m unittest discover tests              testler
.venv\Scripts\python launcher\build_release.py               release zip'i → data\release (PyInstaller,
                                                              ayrı derleme ortamı data\build\venv)
```

---

## 9. AI modu
Sesler program içinde gelmez; ses paketleri (.zip) Ses Kütüphanesi'nden içe aktarılır.

### Kullanım (Ana ekran → "Ses" kartı; ayarlar Gelişmiş görünümde)
- **Mod:** *AI (harici GPU önerilir)*, *DSP (hafif)* veya *Normal ses*. Ctrl+F7 dönüştürmeyi aç/kapa yapar.
- AI modu sadece hız testinin izin verdiği bilgisayarlarda seçilebilir; değilse kutu nedenini yazar.
- **AI sesi:** kurulu sesler. Ses değişince model yeniden yüklenir; o birkaç saniye Discord'a **sessizlik** gider.
- **Perde düzeltme:** otomatik perdenin üstüne ±6 yarım ton. Otomatik perde, konuşanın ortalama perdesini ölçüp
  sesin hedef perdesine çeker; kim konuşursa konuşsun çıkış aynı tonda olur.
- **Tını sadakati (index):** sesin index'i varsa, çıkışı hedef sesin tınısına ne kadar yaklaştıracağı.
- Bu ayarlar ses başına hatırlanır.
- Durum satırı: model durumu, CPU/GPU, işlem süresi, AI gecikmesi, GPU kullanımı ve VRAM, geç kalan parça sayısı.
- **Güvenlik:** model yüklenirken, bir parça geç kalırsa veya hata olursa Discord'a sessizlik gider, asla ham ses.
  Sustuğunda AI çıkışı da susturulur (model sessizlikte kendiliğinden hışırtı üretebiliyor).
- **Ses stüdyosu:** "Yöntem: AI" ile bir kaydı seçili sesle dönüştürüp dinleyebilirsin.

### Hız testi
Ses Kütüphanesi → **Hız testini başlat** (geliştirmede `setup.bat` de çalıştırır). Hız testi CPU'yu ve varsa GPU'ları **oyun benzeri yük altında** ölçer (arka planda sahte bir oyun
çekirdeklerin ~%60'ını meşgul eder); en uygun iş parçacığı sayısını ve parça boyutunu `config\config.json`'a
yazar. Sonuç ekranında GPU kullanımı ve VRAM de görünür.

### GPU hızlandırma (deneysel)
- Varsayılan **kapalı**; her şey CPU'da çalışır. Açıldığında sadece DirectML kullanılır (CUDA kurulmaz).
- Hız testi her GPU'nun sonucunu CPU ile karşılaştırır. **Sonucu CPU'dan farklı çıkan GPU kullanılmaz.**
  Örnek: AMD Radeon 860M (dahili) bu testi geçemedi; RTX 5070 geçti.
- GPU hata verir veya geç kalırsa program sessizce CPU'ya döner ve bunu arayüzde gösterir.

### Ölçümler (Ryzen AI 7 350, 8 çekirdek + RTX 5070 Laptop; oyun benzeri yük altında)
| | Parça | İşlem (%95) | Canlı gecikme | Bizim CPU | GPU / VRAM |
|---|---|---|---|---|---|
| RTX 5070 (DirectML) | 150 ms | 24 ms | ~250 ms | ~%1 | %6–8 / 1.1 GB |
| RTX 5070, GPU %100 doluyken | 150 ms | 92 ms | ~320 ms | ~%3.5 | |
| CPU, 8 iş parçacığı | 250 ms | 165 ms | ~495 ms (**sınırda**) | ~%21 | — |
| CPU, 4 iş parçacığı | 250 ms | 192 ms | ~520 ms ✗ | ~%15 | — |

Canlı gecikme ≈ parça + 50 ms (crossfade) + işlem süresi + ~30 ms (ses kartı ve VB-Cable).
Süre dağılımı (CPU): vocoder ~%60, ContentVec ~%28, perde (FCPE) ~%3, index araması ~%0.2.

### Minimum sistem gereksinimi (tahmin, tek makinede ölçüldü)
- **AI modu, GPU ile (önerilen):** DirectX 12 ekran kartı, hız testindeki CPU-GPU eşitlik testini geçmeli,
  ~1.2 GB boş VRAM. Eşitlik testini geçemeyen GPU (ör. bu makinedeki AMD Radeon 860M) kullanılmaz.
- **AI modu, sadece CPU:** Hız testini oyun yükü altında geçmeli. 8 çekirdekli Ryzen AI 7 350 ancak sınırda
  geçiyor. **Harici GPU'su olmayan çoğu bilgisayarda AI modu oyunla birlikte yetmez.**
- **RAM:** AI modu ~1.5 GB (ortak modeller + bir ses).
- Daha zayıf makinelerde **DSP modu** her zaman çalışır (~%0.5 CPU).

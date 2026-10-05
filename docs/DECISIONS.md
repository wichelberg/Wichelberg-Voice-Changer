# Kararlar

Her karar: tarih, karar, gerekçe. Yeni bir karar eskisini değiştiriyorsa eskisi silinmez, "yerini aldı" diye işaretlenir.

---

## D1 — Platform ve kurulum (2026-10-04)
- Windows, Python 3.11, arayüz tkinter. Paketler **sadece proje içindeki `.venv`'e** kurulur; global Python'a dokunulmaz.
- `requirements.txt` sürümleri sabit; `start.bat` çift tıkla açar, requirements değişince venv'i günceller.
- **Gerekçe:** Kullanıcının isteği; arkadaşlar da aynı ortamı tek tıkla kurabilsin.

## D2 — Ses yolu: VB-Cable, WASAPI (2026-10-04)
- Çıkış `CABLE Input (VB-Audio Virtual Cable)`; Discord/FiveM girişte `CABLE Output` seçer. İsteğe bağlı kulaklık monitörü.
- **CABLE Input her zaman paylaşımlı (shared) modda açılır.**
- Mikrofon yalnızca "düşük gecikme modu" açıkken **ve** çıkış CABLE iken exclusive açılır.
- **Gerekçe:** Geri kayıt testi (CABLE Input'a sinüs, CABLE Output'tan kayıt) özel modda 8 sn'de ~200 kesilme,
  paylaşımlıda 20 sn'de 0 kesilme gösterdi. Çıkış kulaklıkken exclusive mod kulaklığı/mikrofonu kilitleyip
  Discord'u bozmuştu.

## D3 — Kısayollar (2026-10-04)
- Dönüştürme aç/kapa: **Ctrl+F7** (varsayılan), config.json ve arayüzden değiştirilebilir (pynput, oyun içinde de çalışır).
- **Programı kapatan kısayol yok**; kapatma sadece pencereden.
- Favori sesler arası geçiş kısayolu: isteğe bağlı, varsayılan atanmamış.
- **Gerekçe:** F8 FiveM konsolunu açıyor. Kapatma kısayolu yanlışlıkla basılabilir.

## D4 — Güvenlik: ham ses asla kazara gitmez (2026-10-04)
- Program kapanır veya çökerse, işleme hatası olursa, AI modeli takılır veya geç kalırsa, aktif ses değiştirilirken:
  CABLE'a **sessizlik** gider.
- Dönüştürme kapalıyken (Ctrl+F7) / Bypass modunda ham ses **bilinçli olarak** gider.
- **Gerekçe:** Kullanıcının gerçek sesi istemeden duyulmamalı.

## D5 — DSP yöntemi: PSOLA (2026-10-04)
- TD-PSOLA + grain resampling (perde ve formant ayrı). WORLD (pyworld) sadece stüdyoda offline karşılaştırma için.
- AI aşamasında PSOLA **"DSP modu"** olarak yedek mod kalır.
- **Gerekçe:** PSOLA ~27 ms algoritma gecikmesi ve ~%0.5 CPU ile çalışıyor; WORLD gerçek zamanlıda ~10 kat CPU.

## D6 — Klasör düzeni (2026-10-04)
- Kök klasöre üretilen dosya atılmaz. Kayıtlar `data/`, ayarlar `config/`, modeller `models/`. Yollar `voicechanger/paths.py`'de.
- **Gerekçe:** Kullanıcının isteği.

## D7 — Karakter sesi ve seviye (2026-10-04)
- "Hafif yetişkin" preset'i (hafif yetişkin Doğu Asyalı kadın): hedef perde, tonlama, akıcılık, incelik slider'ları.
  Aksan DSP ile değil kullanıcının konuşmasıyla verilir.
- Mikrofon sessiz (~-40 dBFS konuşma) → AutoLevel (AGC, hedef -20 dBFS) + PeakLimiter (-1 dBFS).
- **Gerekçe:** "Ses çok düşük" şikâyeti; slider ile kazanç vermek tutarsızdı.

## D8 — AI yönü (2026-10-04)
- Any-to-one ses dönüşümü; öncelik kalite. İlk sürümlerde **500 ms'ye kadar gecikme kabul**. Konuşma dili Türkçe.
- DSP katmanı AI'ya ön işlem olur: gürültü kapısı, high-pass, AGC.
- Canlı F0 ölçümü (kayan medyan) → aktif sesin `target_f0_median` değerine otomatik perde kaydırma + elle düzeltme slider'ı.
- Arayüzde mod seçimi: AI / DSP / Bypass. AI motoru ayrı modül, ortak arayüz `convert_chunk`.
- **Gerekçe:** Kim konuşursa konuşsun çıkışın hep aynı ses tonunda olması isteniyor.

## D9 — Donanım politikası (2026-10-04) — *eski "sadece CPU, GPU'ya dokunma" kuralının yerini aldı*
- CPU temel platform; her özellik CPU'da çalışmalı.
- Çalışma anında **sadece ONNX Runtime**; torch/CUDA kurulmaz.
- Execution provider tek yerde seçilir (`voicechanger/ai/runtime.py`), varsayılan `CPUExecutionProvider`.
- GPU sadece `onnxruntime-directml` ile, ayarlarda "GPU hızlandırma (deneysel)", varsayılan kapalı.
- GPU hata/zaman aşımı → sessizce CPU'ya dönüş, arayüzde gösterilir.
- CPU ve GPU'da aynı kalite: aynı girdi (rastgele gürültüler dahil) ile karşılaştırma testi.
- Kurulumda hız testi CPU ve GPU'yu ölçer, provider + chunk boyutu önerir, config'e yazar.
- Minimum sistem gereksinimi ölçülüp README'ye yazılır.
- **Gerekçe:** Arkadaşların makineleri farklı; GPU'su olmayan da kullanabilmeli. CUDA/torch kurulumu ağır ve kırılgan.

## D10 — Model ailesi: RVC v2 (ONNX); MeanVC2 şimdilik bırakıldı (2026-10-04)
- Ses modeli formatı RVC v2: içerik kodlayıcı (ContentVec/HuBERT, 768 boyut) + RMVPE perde + NSF-HiFiGAN üretici
  + isteğe bağlı faiss index. Hepsi ONNX.
- MeanVC2 vs RVC offline karşılaştırma aşaması iptal edildi.
- **Gerekçe (MeanVC2):** Çalışma anında torch gerektiriyor (ONNX yolu yok), 16 kHz çıkış (RVC 40/48 kHz),
  Çince/İngilizce için eğitilmiş. Yeni donanım politikasıyla (D9) uyumsuz.
- **Gerekçe (RVC):** MIT lisans, ONNX'e aktarılabilir, index ile tını sadakati, eğitimi Colab'da yaygın ve oturmuş.
- `voice.json` içindeki `model_type` alanı sayesinde MeanVC2 vb. ileride eklenebilir.

## D11 — Çoklu ses tasarımı (2026-10-04)
- Ses paketi: `models/voices/<ses_id>/` → `voice.json` (zorunlu), `model.onnx`, `model.index` (ops.), `preview.wav` (5–10 sn).
- `voice.json`: `schema_version, id, display_name, version, author, description, model_type, embedder, sample_rate,
  target_f0_median, default_index_rate, license, source, consent_note, files[{name, sha256}]`.
- `license` veya `source` boşsa ses **yüklenmez**, uyarı verilir. Her dosyanın sha256'sı doğrulanır.
- `id` klasör adıyla aynı olmalı (a-z, 0-9, `_`).
- Ortak modeller (contentvec, rmvpe) tek kopya: `models/shared/`. Ses paketi sadece kendi modelini taşır.
- `voices/catalog.json` (repoda): id, display_name, version, size_bytes, url, sha256 (zip), license, preview_url, preview_sha256.
- "Ses Kütüphanesi" sekmesi: liste, önizleme, indir/güncelle/sil (sha256 doğrulamalı), sürükle-bırak/İçe aktar.
- Aktif ses yeniden başlatmadan değişir: arka planda yükle → crossfade → eskiyi bırak. Geçişte ham ses gitmez.
- Bellekte sadece aktif model (geçiş anında kısa süre iki model).
- Ses başına ayarlar (perde düzeltme, index_rate, protect…) config'de saklanır.
- **Gerekçe:** Kullanıcının çoklu ses spesifikasyonu.

## D12 — Eğitim ve dağıtım (2026-10-04)
- Eğitim **sadece Colab'da**. Notebook önce lisans/rıza bilgisini ister, sonra eğitir, ONNX'e aktarır, index,
  `target_f0_median`, `preview.wav`, `voice.json` (+ sha256) ve tek bir yayına hazır `.zip` üretir.
- `tools/add_to_catalog.py` zip'i doğrulayıp `voices/catalog.json`'a ekler.
- **Repoya sadece kod girer.** Modeller GitHub Releases veya Hugging Face'te. `config/`, `data/`, `models/` repoya girmez.
- Kod içinde kişiye özel yol yok.
- GitHub reposu henüz yok; adres sonra verilecek.
- `setup.bat` ve Colab notebook'u sıfırdan yazılacak.
- **Gerekçe:** Arkadaşlarla paylaşım; repo hafif ve lisans açısından temiz kalsın.

## D13 — Gerçek kişi sesleri (2026-10-04)
- Gerçek kişilerin sesleri **sadece rızalarıyla** eklenebilir; README'de açıkça yazılır. İzinsiz ünlü/karakter klonu eklenmez.

## D14 — Sürükle-bırak (2026-10-04)
- `tkinterdnd2` (MIT) kullanılır. Yüklenemezse uygulama çökmez; sadece "İçe aktar…" butonu çalışır.

## D15 — Faz sırası (2026-10-04)
1. Çekirdek: runtime, ses paketi doğrulama, ONNX RVC çıkarımı, CPU-GPU eşitlik testi, hız testi.
2. Gerçek zamanlı: AI modu motorda, otomatik perde, geç kalırsa sessizlik, Canlı sekmesi göstergeleri.
3. Ses Kütüphanesi: katalog, indirme, içe aktarma, crossfade ile ses değişimi, ses başına ayarlar.
4. Hat ve dokümanlar: Colab notebook, add_to_catalog.py, README, SES_EKLEME.md.
- Her fazdan önce plan sunulur, onay beklenir.

## D16 — Tek seferlik geliştirme istisnası: geçici CPU-torch ortamı (2026-10-04)
- 1. fazı test edebilmek için RVC'nin açık lisanslı taban modeli (pretrained v2, MIT kod / VCTK CC-BY-4.0 veri)
  **proje içinde ayrı bir klasördeki geçici CPU-torch ortamında** ONNX'e çevrilir.
- Bu ortam iş bitince **silinir**. Bu taban model **kataloğa ve repoya girmez**; sadece geliştirme testi içindir.
- Bu, D9'daki "torch kurma" kuralına bilinçli ve tek seferlik bir istisnadır; kullanıcı onayladı.
- **Gerekçe:** İlk gerçek ses Colab'da eğitilene kadar ONNX hattını test edecek bir model gerekiyor.
- **Uygulama (2026-10-04):** Ortam `.dev_export/` klasöründe kuruldu (CPU torch 2.x). Aynı ortamda test sesine ek
  olarak ortak modeller de (contentvec, fcpe, rmvpe) ONNX'e çevrildi; çünkü hattın test edilmesi için bunlar da
  gerekiyordu. Test sesi: `models/voices/dev_rvc_base` (pretrained_v2 f0G40k, VCTK konuşmacı sid 70; 109 konuşmacı
  arasından spektral merkezi en yüksek olan seçildi). Kataloğa ve repoya girmez. Ortam iş bitince silindi.

---

## D17 — İçerik kodlayıcı kaynağı: lengyue233/content-vec-best (MIT) (2026-10-04)
- RVC'nin `hubert_base` dosyası ile ağırlıklar aynı (fp16'ya yuvarlanınca fark 0.0, ölçüldü).
- **Gerekçe:** lj1995/VoiceConversionWebUI (HF) deposundaki lisans dosyasında MIT metninin üstünde Çince
  "yalnızca araştırma amaçlı" şartı var. Aynı ağırlığın temiz MIT kaynağı tercih edildi.

## D18 — Perde (F0) modeli: varsayılan FCPE (MIT); RMVPE isteğe bağlı (2026-10-04)
- `config.json → ai.pitch_method`: `fcpe` (varsayılan) | `rmvpe`.
- **Ölçüm (kullanıcının 10 sn kaydı, Harvest referans):** ortak ötümlü karelerde medyan fark FCPE 8.7 cent,
  RMVPE 10.8 cent; FCPE 2.6 kat hızlı; dosya 46 MB (RMVPE 366 MB); uçtan uca fark 1.68 dB (iki farklı gürültüyle
  aynı dönüşümün kendi farkı 2.45 dB, yani ayırt edilemez).
- **Gerekçe:** RMVPE ağırlıkları lj1995 HF deposundan; "yalnızca araştırma" şartı taşıyor. FCPE eşdeğer kalitede,
  MIT ve hafif.

## D19 — ONNX arayüzü ve dışa aktarma: `training/export_onnx.py` (2026-10-04)
- Tüm rastgelelik girdi: `rnd` (akış gürültüsü) ve `noise` (NSF kaynak gürültüsü) mutlak kare indeksine bağlı sabit
  tablodan gelir. CPU/GPU ve akış/offline aynı gürültüyü görür (eşitlik testinin ön şartı).
- `phase` girdisi: harmonik kaynağın fazı parçadan parçaya devam eder (RVC'nin kendi gerçek zamanlısında yok).
- Göreli konum dikkati (attention) dinamik uzunluk için tensör işlemleriyle yeniden yazıldı; RVC'nin `infer`'i ile
  birebir aynı (fark 0), ONNX her uzunlukta torch ile SNR ≥ 94 dB.
- Perde modellerinde mel spektrogram grafiğin içinde (STFT konvolüsyonla): çalışma anında sadece ham ses verilir.
- Klasör: plan `notebooks/` diyordu; içinde betik de olacağı için `training/` yapıldı (Colab notebook da buraya).

## D20 — Akış tasarımı (2026-10-04)
- Pencere = [bağlam 1000 ms | crossfade 40 ms | SOLA arama 10 ms | yeni parça]. Üretici sadece son
  (crossfade + arama + parça) kısmı sentezler (`skip_head`/`return_length`).
- Canlı gecikme ≈ parça + 50 ms + işlem süresi + ~30 ms ses kartı/VB-Cable.
- Parça boyutu hız testinden gelir (`ai.stream.block_ms`); işlem, parçanın en çok %75'i olmalı.
- Kenar payı (margin) 0: 40 ms pay kaliteyi ölçülebilir şekilde değiştirmedi (4.30 → 4.34 dB), işi %12 artırıyordu.

## D21 — GPU ayrıntıları (2026-10-04)
- DirectML sadece sabit girdi boyutunda hızlı: GPU'da her oturum bir parça boyutuna sabitlenir
  (`free_dimension_override`). Boyut sabitlenmezse ilk çalıştırmanın boyutu dışındakiler ~6 kat yavaş.
- FCPE sabitlenmez: DirectML'de sabit boyutla yanlış perde veriyor (ölçüldü). Akışta hep aynı boyutla çağrıldığı
  için yine hızlı yola giriyor.
- **AMD Radeon 860M (dahili) eşitlik testini geçemedi** (ContentVec çıktısı SNR 18 dB). Hız testi her GPU için
  eşitliği ölçüp config'e yazar; geçemeyen GPU seçilse bile kullanılmaz (`Runtime.from_settings`).
- Varsayılan GPU: en çok VRAM'li gerçek GPU (bu makinede RTX 5070 Laptop).
- **Eşitlik testini geçemeyen GPU ayarlarda gösterilmez / otomatik kapalı kalır** (kullanıcı kararı, 2026-10-04).
  Ölçü cihaz bazında, marka bazında değil: hız testi her GPU için `parity_ok` yazar. Test edilmemiş GPU,
  açılmadan önce eşitlik testinden geçirilir. Hiç geçen GPU yoksa GPU seçeneği gizlenir.

## D22 — int8 nicemleme kullanılmıyor (2026-10-04, ikinci ölçüm 2. faz başında)
Ölçüm: 30 sn konuşma (CMU ARCTIC bdl), parça 200 ms; kalite fp32 çıktısına göre. Taban (aynı fp32, sadece
farklı gürültü): spektral 2.29 dB.

| Varyant | Hız 8 / 4 iş p. | Spektral fark (medyan / %95) | Karar |
|---|---|---|---|
| fp32 | 135 / 157 ms | 0 | kullanılıyor |
| ContentVec dinamik int8, kanal başına | 123 / 147 ms (−%9) | 0.23 / 0.77 dB | en iyi aday; kazanç küçük |
| ContentVec dinamik int8 (tensör başına / u8) | 120 / 148 ms | 0.40–0.48 dB | — |
| ContentVec statik QDQ (MatMul+Conv) | 112 / 144 ms | 2.26 / 7.30 dB | ✗ bozuyor |
| Üretici statik QDQ (resblock Conv) | 105 / 124 ms (−%22) | 3.21 / 7.85 dB | ✗ tabanın üstünde |
| Üretici statik QDQ (tüm Conv) | 111 / 122 ms | 3.91 / 9.36 dB | ✗ |
| Üretici dinamik (ConvInteger) | 10 kat yavaş | — | ✗ |

- Karar: fp32 kalıyor. Tek makul aday (ContentVec dinamik, kanal başına) %9 kazandırıyor ve CPU ile GPU
  çıktısını farklılaştırır (D9 "aynı kalite"). Dinleme dosyaları: `data/outputs/optimizasyon/`.
- Nicemleme torch'suz geçici bir ortamda (`.dev_quant/`: onnx + onnxruntime) yapıldı ve silindi.

## D23 — Ölçülen performans (2026-10-04, Ryzen AI 7 350 8C/16T + RTX 5070 Laptop)
Bileşen payı (CPU, parça 200 ms, 8 iş p., toplam ~126 ms): üretici %66 (içinde vocoder resblock'ları %61,
kodlayıcı %19, ConvTranspose %8, akış %6), ContentVec %28, FCPE %3, index araması %0.2, yeniden örnekleme %1.4.
Vocoder maliyeti üretilen sesin saniyesi başına sabit; parça başına sabit kısım (ContentVec bağlamı) büyük
parçayla azalır.

Oyun benzeri yük altında (10 süreç × 60 FPS, mantıksal çekirdeklerin ~%60'ı; gerçek zamanlı tempo):

| Ayar | %95 işlem | Geç kalan | Bizim CPU | Canlı gecikme |
|---|---|---|---|---|
| CPU 8 iş p., parça 250 ms | 165 ms | 0 | %21 | ≈ 495 ms (sınırda geçti) |
| CPU 6 iş p., parça 200 ms | 158 ms | 0 | %19 | ≈ 438 ms (%79: pay yetersiz) |
| CPU 4 iş p., parça 250 ms | 192 ms | 0 | %15 | ≈ 522 ms ✗ |
| CPU 2 iş p. | parçadan uzun | hepsi | %11 | ✗ |
| RTX 5070, parça 150 ms | 24 ms | 0 | %0.9 (GPU %8, VRAM 1.1 GB) | ≈ 254 ms |
| RTX 5070, GPU %100 doluyken | 92 ms | 0 | %3.5 | ≈ 322 ms |

- Aşırı yükte (14 süreç, çekirdekler neredeyse dolu) CPU yolu parça kaçırmaya başlıyor (6 iş p.: 1/38 geç).
- Süreç önceliğini yükseltmek fark etmedi. ORT "spinning" açıkken daha yavaş ve +%10-25 CPU: kapalı kalır.
- Bağlam 1000 → 700 ms: %7 hız, +0.28 dB. Crossfade 40 → 20 ms: kazanç yok. Varsayılan 1000 ms kalır.
- Index araması hızı etkilemiyor (D25 düzeltmesinden sonra); sese etkisi index oranına göre 0.9–2.7 dB.
- Sahte oyunun kare hızına etkimiz CPU modunda ölçülemeyecek kadar küçük; GPU %100 doluyken −%7..11.
  Gerçek oyunla (FiveM) 2. fazda canlı ölçülecek.

## D24 — Eğitimde kullanılacak ön-eğitim (pretrained) modeli: araştırma (2026-10-04; karar 4. fazdan önce)
RVC'de ses, bir ön-eğitim modelinden ince ayarla eğitilir; ses modelinin lisans zinciri bu modele de bağlıdır.

| Ön-eğitim | Etiketlenen lisans | Neyin üstüne / hangi veri | Değerlendirme |
|---|---|---|---|
| RVC resmi pretrained_v2 (lj1995) | MIT + Çince "yalnızca araştırma" notu | sıfırdan; VCTK (CC BY 4.0) | şu anki taban; not belirsizlik yaratıyor |
| TITAN (blaise-tk) | Apache-2.0 | resmi RVC v2'den ince ayar; Expresso 11 sa (**CC BY-NC 4.0**) | zincir temiz değil (araştırma notu + ticari olmayan veri) |
| Ov2 Super (ORVC) | MIT | resmi RVC v2'nin "refinement"ı; veri belirtilmemiş | zincir belirsiz |
| KLM 4.1 (SeoulStreamingStation) | özel: kişisel/eğitim/araştırma; kişisel platformda ticari serbest; modelin satışı yasak | taban ve veri kaynağı belirtilmemiş | izin verici değil |
| SingerPreTrain (Sztef) | OpenRAIL | belirtilmemiş, şarkıcı verisi | konuşma için değil, belirsiz |
| RIN_E3, SnowieV3.1 (MUSTAR), Nanashi, DMR | **lisans yok** | kaynak belirtilmemiş | kullanılamaz (varsayılan: tüm hakları saklı) |
| **Kendi ön-eğitimimiz (sıfırdan)** | kod MIT | VCTK (CC BY 4.0) + LibriTTS-R (CC BY 4.0) + Common Voice Türkçe (CC0) | tek tamamen temiz yol; maliyet yüksek |

- Bulgu: hazır, lisans zinciri tamamen temiz bir RVC ön-eğitim modeli bulunamadı. Topluluk modellerinin hemen
  hepsi resmi RVC v2'den ince ayar.
- Kalite farkı ölçülemedi (eğitim gerekir). Topluluk raporlarına göre TITAN/Ov2/RIN az veriyle (1-10 dk) resmi
  modelden iyi; doğrulanmadı.
- Kendi ön-eğitimimiz: RIN_E3 ölçeğinde ~1M adım (RTX 4080/A100 sınıfında günler). Ücretsiz Colab'da pratik değil.
- Kaynaklar: huggingface.co/blaise-tk/TITAN, huggingface.co/ORVC/Ov2Super, huggingface.co/SeoulStreamingStation/KLM4.1
  (LICENSE), huggingface.co/MUSTAR/RIN_E3, docs.applio.org/getting-started/pretrained, arxiv.org/abs/2308.05725.

## D25 — faiss tek iş parçacığı (2026-10-04)
- `faiss.omp_set_num_threads(1)`. Arama ~0.2 ms; ama varsayılan OpenMP iş parçacıkları aramadan sonra 16
  çekirdekte boşta dönüp bekliyordu: toplam CPU %12 → %51, ONNX %30 yavaş (ölçüldü). İlk hız testindeki
  "%23 CPU" da yanlış bir tahmindi; hız testi artık CPU'yu gerçek zamanlı tempoda ölçüyor.

## D26 — Hız testi oyun yükü altında ölçer (2026-10-04)
- Parçalar gerçek zamanlı tempoda; arka planda sahte oyun (`voicechanger/tools/loadsim.py`, mantıksal
  çekirdeklerin ~%60'ı). İş parçacığı sayısı ve parça boyutu bu koşulda seçilir.
- Geçme şartı: geç kalan parça 0, %95 işlem ≤ parçanın %75'i, canlı gecikme ≤ 500 ms.
- Sonuç `config.json → ai.benchmark` (`cpu_ai_ok`, GPU başına `parity_ok`, GPU kullanımı, VRAM).
- GPU kullanımı/VRAM: `voicechanger/ai/gpustats.py` (Windows PDH sayaçları; her marka GPU).

## D27 — Minimum donanım (2026-10-04)
- **AI modu, GPU ile (önerilen):** DirectX 12 ekran kartı; hız testindeki CPU-GPU eşitlik testini geçmeli;
  ~1.2 GB boş VRAM. Ölçülen: RTX 5070 Laptop, GPU %6-8, CPU %1, ≈ 254 ms.
- **AI modu, sadece CPU:** hız testi oyun yükü altında geçmeli. Bu makine (8 çekirdek Zen 5/5c, 2025) ancak
  sınırda geçiyor (8 iş p., ≈ 495 ms, CPU %21). Bundan zayıf işlemciler (≤ 6 çekirdek veya eski nesil) büyük
  ihtimalle geçemez. Tek makinede ölçüldü: tahmin.
- **Açıkça: harici GPU'su olmayan çoğu bilgisayarda AI modu oyunla birlikte yetmez.** Öneri: AI modu "GPU
  ister" diye tanıtılsın; CPU'da sadece hız testini geçen makinelerde açılsın; diğerleri DSP modunu kullansın.
  Kullanıcıyla konuşulacak.
- Kalan CPU seçenekleri (yapılmadı): 32 kHz ses modelleri (vocoder ~%16 daha az iş, teorik hesap), daha küçük
  üretici ile eğitim (kalite riski).

## D28 — Kullanıcının makinesinde GPU açık (2026-10-04)
- Kullanıcı kararı: kendi `config.json`'unda `ai.runtime.accel = "gpu"` (RTX 5070, device 0), parça 150 ms.
  Yeni kurulumda varsayılan yine CPU (D9).

## D29 — Test verisi (2026-10-04)
- Ölçümler için CMU ARCTIC "bdl" (erkek, ABD İngilizcesi) 150 cümle: `data/testsets/cmu_arctic_bdl/` (repoya
  girmez). Lisans: her amaçla serbest, telif notu korunmalı (COPYING klasörde).
- Test sesinin index'i bu verinin 1-100. cümlelerinin dönüştürülmüş hâlinden (14k vektör, IVF360); 101+
  değerlendirmeye ayrıldı.

## D30 — AI modu kimde açık (2026-10-04)
- Kullanıcı kararı: AI modu **"harici GPU önerilir"** diye tanıtılır.
- GPU yolu: hız testinde CPU-GPU eşitlik testini geçen GPU varsa açılabilir.
- CPU yolu: sadece hız testinin **oyun yükü altında** geçtiği makinelerde (`ai.benchmark.cpu_ai_ok = true`).
  Hız testi yoksa veya geçmediyse AI modu CPU'da kapalıdır; arayüz nedenini söyler ve DSP modunu önerir.
- DSP modu her makinede çalışır.

## D31 — Ön-eğitim modeli: resmi RVC pretrained_v2; repo özel (2026-10-04)
- Kullanıcı kararı: D24 seçenek (a). Colab eğitimi resmi RVC pretrained_v2 (lj1995) ile yapılır.
- GitHub reposu **özel (private)**, sadece arkadaş grubu. Eğitilen sesler herkese açık yayınlanmaz; ticari kullanım yok.
- **Proje herkese açılırsa lisans yeniden değerlendirilmeli** (lj1995 ağırlıklarındaki "yalnızca araştırma" notu;
  RMVPE için aynı not; seçenek: D24'teki temiz kendi ön-eğitimimiz).

## D32 — Canlı AI yolu (2026-10-04, 2. faz)
- Ses kartı callback'i (10 ms): high-pass → gürültü kapısı → otomatik seviye → `AiLive.push`; çıktı `AiLive.pull`.
  Model ayrı iş parçacığında (`voicechanger/ai/live.py`) çalışır; callback hiç beklemez.
- Çıkış zamanlaması: her parça, son 40 parçanın %95 işlem süresi + 10 ms'ye göre planlanır
  (AI gecikmesi ≈ parça + bu süre + 50 ms crossfade). Plan başlangıçta hız testi değerinden gelir.
- Parça zamanında gelmezse o an SESSİZLİK, sayaç artar, tampon yeniden kurulur. Tampon fazla birikirse
  sessiz bölgeden kırpılır (100 ms'yi aşarsa zorla). Kuyruk dolarsa en eski parça atlanır.
- Model arka planda yüklenir (+2 ısınma çalıştırması: DirectML grafiği derlensin); hazır olana kadar sessizlik.
- GPU'da parça başına zaman aşımı 2 × parça; aşılırsa CPU'ya döner (D9).

## D33 — AI çıkışında sessizlik maskesi (2026-10-04)
- Ölçüm: RVC tamamen sessiz girişte de ~0.2 tepeli ses/gürültü üretiyor (konuşmadan önce de sonra da).
- Karar: girişin sessiz olduğu (kapının kapattığı, < -70 dBFS) 10 ms'lik kareler, gecikmeyle hizalanıp çıkışta
  susturulur; ±1 kare pay (konuşmanın başı/sonu kesilmesin), 5 ms rampa. Stüdyoda da aynısı.

## D34 — Mod ve aç/kapa anlamı (2026-10-04)
- Arayüzde "Mod": AI / DSP / Normal ses. Ctrl+F7 dönüştürmeyi aç/kapa yapar (kapalı = normal ses), seçili mod
  hatırlanır (`ai.mode`).
- Mod değişimi 10 ms kısma/açma ile. AI'ya geçerken AI'nın eski bağlamı silinir.
- Dönüştürme kapalıyken söylenenler, açılınca AI'dan tekrar çalınmaz (o parçalar atılır).
- AI dönüştürücü DSP moduna geçince bellekte kalır (hızlı geri dönüş); ses değişince yeniden yüklenir
  (3. fazda crossfade ile değişim gelecek).

## D35 — Stüdyoda AI (2026-10-04)
- Stüdyo dönüştürmesi canlı yolun aynısı (ön işlem + sessizlik maskesi), ama ayrı bir model örneğiyle CPU'da
  ve dinamik boyutla çalışır: canlıdaki GPU oturumu sabit boyutlu (D21), ona dokunulmaz. Bellekte tek stüdyo modeli.
- Otomatik perde stüdyoda kaydın medyan F0'ından (DIO) hesaplanır.

## D36 — Kelime sonu yutma düzeltmesi (2026-10-04) — **GERİ ALINDI (aynı gün, D38)**
- Şikâyet: Türkçe konuşurken kelime sonları yutuluyor.
- Neden (ölçüldü): gürültü kapısı ham mikrofon seviyesinde -45 dBFS eşikle çalışıyor; kullanıcının konuşma
  medyanı -46 dBFS. Kelime sonu kısılınca 6 dB histerezis + 150 ms hold sonrası kapı kapanıyordu. AI modunda
  model kapılı girişi aldığı için kelime sonunu hiç görmüyordu.
- Ölçüm (150 ARCTIC cümlesi kullanıcının seviyesine indirilmiş + kullanıcının kaydı):
  şu an konuşma kaybı %6.2, son 150 ms'si %30'dan fazla kesilen kelime sonları %7.0.
- Düzeltme:
  - Kapı histerezisi 6 → 15 dB (DSP'de kayıp %2.8 / %1.9). Kapanma eşiği gürültü tabanının en az 6 dB üstünde
    kalır (taban, minimum takibiyle izlenir) → gürültülü mikrofonda kapı açık kalmaz.
  - AI modu: model sesi kapısız alır; kapının kararı çıkış susturması olur, 50 ms ileri bakış + 100 ms kuyruk
    (kayıp %0.7 / %1.0). Stüdyoda da aynısı. D33'ün yerini aldı (susturma artık girişin seviyesine değil kapının
    kararına bakıyor).

## D37 — Yeni DSP presetleri ve "Titreme" (2026-10-04)
- Yeni slider "Titreme (yaşlı ses)": perde ±60 cent × ayar ve şiddet ±%30 × ayar, 4.5-6.5 Hz arasında gezinen
  hızda (mekanik duyulmasın). Ölçüm: %45'te sabit sesli harfte ±19 cent std, 5.5 Hz.
- Yeni hazır presetler: Olgun kadın (200 Hz), Yaşlı kadın (185 Hz, pürüz, nefes %30, titreme %45),
  Yaşlı adam (120 Hz, titreme %50), Derin erkek (95 Hz, formant 0.92). Hedef perde slider'ı 80 Hz'e kadar iner.
- Değerler literatürdeki yaşlı ses özelliklerinden (daha pes F0, jitter, nefes, tremor) seçildi; kulakla ince
  ayar kullanıcıya bırakıldı. Dinleme: data/outputs/preset_*.wav.
- AI modunda yaşlı kadın sesi için ayrı bir eğitilmiş ses modeli gerekir (4. faz, rıza/lisans şartıyla).

## D38 — D36 geri alındı (2026-10-04)
- Kullanıcının arkadaşları D36'dan sonra sesi hafif kötü buldu; kullanıcı üç değişikliğin de geri alınmasını istedi.
- Geri alınanlar: kapı histerezisi tekrar 6 dB (gürültü tabanı takibi yok); AI girişi tekrar kapılı; AI çıkış
  susturması tekrar giriş seviyesine göre ±10 ms (D33). Presetler ve "Titreme" (D37) kalıyor.
- Muhtemel neden (doğrulanmadı): kapısız giriş + otomatik seviye kazancı nefesi/arka plan gürültüsünü modele
  veriyor, RVC bunu garip seslere çeviriyor; uzun açık kalan susturma bunları duyuruyordu. D36'nın ölçümünde
  sessizlikte açık kalma %33 → %63 çıkmıştı; bu yan etki yanlışlıkla önemsiz sayıldı.
- Ders: canlı sesi değiştiren bir ayarda tek bir ölçüye (kelime sonu kaybı) göre değil, yan etkilerle (aralarda
  sızan ses) birlikte karar ver ve kullanıcıya önce/sonra dinleme dosyası ver.
- Kelime sonu yutma sorunu açık; yeniden ele alınırsa önce A/B dosyaları ile.

## D39 — Yaşlı kadın AI sesi: Common Voice (2026-10-04)
- Kullanıcı kararı: yaşlı kadın AI sesi 4. fazda Common Voice (CC0) verisinden, yaş/cinsiyet etiketli yaşlı kadın
  konuşmacılardan eğitilecek. Tek bir kişiyi taklit etmemek için birden çok konuşmacının karışımı tercih edilir.

## D40 — Mevcut kadın sesi donduruldu; öncelik yaşlı kadın (2026-10-04)
- Kullanıcı kararı: şu anki canlı kadın sesi "mükemmel sonuç"; **dokunulmaz**. Bu ses **AI modundaki
  `dev_rvc_base` sesidir** (kullanıcı netleştirdi; "Jaen Mao" DSP preseti kapsam dışı, önemi yok).
  Kapsam: `dev_rvc_base` dosyaları (model.onnx, model.index, voice.json), ses başına ayarları ve canlı AI yolunun
  ses davranışı (ön işlem, kapı, susturma, akış ayarları, ContentVec/FCPE modelleri, `rvc_onnx.py` çıkarımı).
  Bunları etkileyen her değişiklik önce kullanıcıya önce/sonra dinleme dosyasıyla sunulur ve açık onay ister.
- Sıra: önce yaşlı kadın AI sesi (Common Voice, D39), sonra Doğu Asyalı genç kadın sesi (AISHELL-3, deneme).

## D41 — Dondurulan AI sesinin kimliği, yedeği ve yeniden üretim tarifi (2026-10-04)
- Dosyalar (sha256):
  - `model.onnx` 867c3be7a5c94a33b883b4aef09614ac6a858c79b550cde19be7d3023eab9792
  - `model.index` e946448607b03ad41d8ebd09ea73541f8b65724cfced75ba693813fe1a35eaca
  - ortak: `contentvec.onnx` 41b51e0f…12d10, `fcpe.onnx` d184325f…36aeb (tam değerler `shared.py`'de)
- Kullanılan ayarlar: index_rate 0.5, protect 0.33, perde düzeltme 0, hedef F0 220 Hz (voice.json), perde FCPE,
  GPU (RTX 5070), parça 150 ms, bağlam 1000 ms.
- Yedek: `data/yedek/ana_kadin_sesi_dev_rvc_base_2026-10-04.zip` (dosyalar + ayarlar.json). Repoya girmez.
- Yeniden üretim (yedek kaybolursa; torch gerekir → Colab):
  1. `lj1995/VoiceConversionWebUI` → `pretrained_v2/f0G40k.pth` indir.
  2. `python training/export_onnx.py voice --src f0G40k.pth --out model.onnx --sid 70` (RVC kaynağı gerekir).
  3. Index: CMU ARCTIC bdl `arctic_a0001…a0100`, bu sesle offline dönüştürülüp ContentVec öznitelikleri
     (IVF{16·√N}, nprobe 1; o zaman 14 077 vektör, IVF360). Rastgelelik nedeniyle index birebir aynı çıkmayabilir.
- Not: D16'da bu ses "sadece geliştirme testi, kataloğa/repoya girmez" diye kaydedilmişti. Arkadaş grubuyla
  paylaşılıp paylaşılmayacağı ayrıca karara bağlanacak (lisans: VCTK CC BY 4.0 → atıf gerekir; RVC ön-eğitim
  ağırlıklarında "yalnızca araştırma" notu, repo özel olduğu için D31 kapsamında değerlendirilebilir).

## D42 — Ana kadın sesi arkadaş grubuyla paylaşılıyor (2026-10-04)
- Kullanıcı kararı: dondurulan AI sesi (D40, D41) özel arkadaş grubuyla paylaşılır. D16'daki "sadece geliştirme
  testi, kataloğa girmez" kaydının yerini alır (sadece bu ses için).
- Kalıcı ad: `models/voices/ana_kadin`, "Ana kadın sesi" (eski id `dev_rvc_base`). Model ve index dosyalarına
  dokunulmadı (sha256 aynı); kullanıcının kaydı üzerinde çıktı ad değişikliğinden önce ve sonra birebir aynı.
- voice.json lisansı: VCTK CC BY 4.0 (atıf: CSTR, University of Edinburgh) + RVC ağırlıkları (MIT +
  "yalnızca araştırma" notu). Sadece özel grup, ticari değil, herkese açık yayımlanmaz (D31).
- Dağıtım: model dosyaları git'e girmez (repoya sadece kod, D12; ayrıca model.onnx 105 MB > GitHub'ın 100 MB
  dosya sınırı). Özel reponun **GitHub Releases**'ına yüklenir (özel repoda Releases da özeldir). Ses Kütüphanesi
  (3. faz) gelene kadar arkadaş zip'i elle `models/voices/` altına açar.

## D43 — Common Voice kullanım şartlarına uyum (2026-10-05)
- Veri seti: Common Voice Scripted Speech 27.0 - Turkish (Mozilla Data Collective, CC0-1.0, ~2.7 GB).
- Şartlar: konuşmacıların kimliğini belirlemeye çalışmak yasak; veri setini yeniden barındırmak/paylaşmak yasak.
- Uyum: seçim sadece yaş/cinsiyet etiketiyle, birden çok konuşmacının karışımı (D39); ham kayıtlar ve seçilen
  eğitim klipleri hiçbir yere yüklenmez (GitHub, Releases, Drive, arkadaşlar) — sadece Colab oturumunda kalır.
  Paylaşılan tek şey eğitilmiş model + index. `preview.wav` veri setinden bir klip değil, başka bir cümlenin bu
  sesle dönüştürülmüş hâlidir.
- İndirme: MDC API (anahtar sadece Colab Secrets'ta `MDC_API_KEY`; repoya/sohbete/dosyalara yazılmaz).
- Ek: aynı hatta 20-30 yaş kadın sesi de deneme olarak eğitilecek (kullanıcı isteği); yaşlı kadın önce.

## D44 — Colab eğitim notebook'u (2026-10-05)
- `training/colab_ses_egitimi.ipynb`, `training/build_notebook.py` ile üretilir (elle düzenlenmez; export_onnx.py
  içine gömülür, böylece ONNX biçimi uygulamayla birebir aynı kalır).
- Ayarlar: SES_TURU (yasli_kadin | genc_kadin), hedef 25 dk, en çok 6 konuşmacı (biri en çok %40), 200 epoch,
  RVC v2 40k, RVC kodu commit 81eed5e (export_onnx.py bununla doğrulandı), ContentVec = content-vec-best (D17),
  eğitim F0'ı RMVPE (D31 kapsamında).
- Seçim: Common Voice etiketleri (kadın + yaş) + kalite (SNR ≥ 25 dB, kırpılma yok, perde aralığı); konuşmacılar
  sadece numarayla gösterilir; kullanıcı dinleyip onaylar / çıkarır.
- Drive'a sadece model ağırlıkları (kaldığı yerden devam için) yazılır; ses verisi yazılmaz (D43). Son hücre veriyi siler.
- Durum: yazıldı, sözdizimi denetlendi; **Colab'da henüz çalıştırılmadı** (yerelde torch yok, D9). İlk çalıştırmada
  hata çıkarsa düzeltilecek.
- Güncelleme (2026-10-05): ücretsiz Colab RVC'yi "deepfake" yasağıyla durdurdu (D45). Notebook ücretli Colab için
  yerinde kalır; asıl eğitim yolu artık laptop (D45).

## D45 — Eğitim kullanıcının bilgisayarında (RTX 5070), ayrı ortamda (2026-10-05)
- Durum: Ücretsiz Colab, RVC eğitimini "deepfake" yasağı kapsamında durdurdu (2022'den beri ücretsiz katmanda yasak;
  tespit kod/proje kara listesiyle, hangi satırın tetiklediği açıklanmıyor). Tespitten kaçmaya çalışılmaz.
- Kullanıcı kararı: eğitim laptopta (B seçeneği). **D12'deki "eğitim sadece Colab'da" ve CLAUDE.md kural 4'e istisna.**
  Kullanıcı ileride başka eğitimler için ücretli Colab'ı da kullanabilir (yasak sadece ücretsiz katmanda).
- Sınırlar: eğitim ortamı (torch + CUDA 12.8, RVC kodu, eğitim verisi, ara çıktılar) sadece `data/egitim/` altında
  durur (repoya girmez). Uygulamanın `.venv`'i değişmez, çalışma anında torch yok (D9 aynen geçerli).
- Güvenlik: eğitim sırasında GPU sıcaklığı izlenir; 85 °C'de eğitim duraklatılır, 75 °C'ye inince devam eder
  (kullanıcı isteğiyle 87 → 85, 2026-10-05).
- Varsayılanlar: 15 dk veri, 200 epoch, 100/150/200. epoch'larda ara model + dinleme dosyası; kullanıcı seçer.
- Colab notebook'u (D44) ücretli Colab için yerinde kalır.

## D46 — Common Voice verisi saklanmaz, gerektiğinde yeniden indirilir (2026-10-05)
- Kullanıcı veriyi Google Cloud'a yüklemeyi önerdi; önerilmedi: MDC şartları "yeniden barındırma/paylaşma"
  yasaklıyor (D43) ve gerek yok (yeniden indirmek ücretsiz, birkaç dakika, günde 30 hak).
- Veri, kullanıcının web arayüzünden indirdiği `.tar.gz` ile gelir (sha256 doğrulanır; API anahtarı gerekmez);
  eğitimler bitince `data/egitim/` altından silinir.

## D47 — Yerel eğitim hattı: `training/egitim.bat` + `training/yerel_egitim.py` (2026-10-05)
- Ortam: `data/egitim/venv` (Python 3.11, torch 2.7.1+cu128, `training/requirements-egitim.txt`), RVC kodu
  commit 81eed5e `data/egitim/rvc`. Uygulamanın `.venv`'i değişmedi.
- Komutlar: kur → veri → sec → onay → egit → adaylar → paketle → temizle. Her adım kaldığı yerden devam eder.
- Uçtan uca test edildi (CMU ARCTIC'ten sahte mini veri seti, 2 epoch): seçim, ön işleme, perde/öznitelik, eğitim,
  index, adaylar, ONNX (RVC ile fark 0, ONNX SNR ≥ 97 dB), voice.json, zip, kurulum; paket uygulamanın kendi
  ortamında doğrulandı ve CPU offline + GPU akışta dönüştürdü. Test kalıntıları silindi.
- Bulunan ve çözülen sorunlar:
  - RVC betikleri kök klasörü modül yolunda bekliyor → `PYTHONPATH=rvc`, `PYTHONSAFEPATH=1` (yoksa `import train`
    train/train.py'yi buluyor).
  - RVC sesi `ffmpeg` programıyla okuyor, bilgisayarda yok → `imageio-ffmpeg` (BSD-2) ile gelen ffmpeg.exe
    `data/egitim/bin`'e kopyalanır (sadece eğitim ortamında; uygulama ffmpeg kullanmaz).
  - RVC ön işleme hata olunca sessizce boş çıktıyla devam ediyor (ilk denemede model sadece sessizlikle eğitildi) →
    her adımdan sonra parça sayısı denetlenir, eksikse durur.
- Gözlem: kalite eşiği SNR ≥ 25 dB; stüdyo kalitesindeki ARCTIC bile bu ölçüyle 28-29 dB çıktı. Common Voice'ta çok
  konuşmacı elenirse eşik birlikte ayarlanacak.

## D48 — Yaşlı kadın AI sesi eğitildi: `models/voices/yasli_kadin` (2026-10-05)
- Veri: Common Voice Türkçe 27.0, etiket "kadın" + 60 yaş üstü; en az 25 klibi olan 5 aday, 5'i de kalite eşiğini
  geçti; kullanıcı dinleyip 4. konuşmacıyı (arka plan sesi) çıkardı. 4 konuşmacı × 3.8 dk = 15 dk (304 parça;
  1 tamamen sessiz parça atlandı).
- Eğitim: laptop RTX 5070, RVC v2 40k, pretrained_v2'den ince ayar, 200 epoch, batch 8, **65 dk**, ~20 sn/epoch,
  GPU ~75 °C, VRAM ~7/8 GB, sıcaklık duraklaması olmadı. Index: 33 610 vektör (IVF861).
- Aday seçimi (kullanıcı "sana güveniyorum" dedi; ölçüyle seçildi): epoch 100/150/200 hepsinde perde hedefte
  (~184 Hz; hedef = eğitim verisinin medyanı 180.6 Hz), ani sıçrama 0. Kullanıcının kaydında eğitim verisine tını
  farkı 5.06 / 5.05 / **4.93 dB** → **epoch 200** seçildi (fark küçük).
- Uygulamada doğrulandı: paket yüklendi; stüdyo (CPU) kullanıcının sesini 174 → 182 Hz'e çevirdi; GPU canlı akış
  150 ms parçada işlem medyan 26 / %95 30 ms. Dinleme: `data/outputs/kayit_yasli_kadin_AI.wav`.
- Boyut: model.onnx 105 MB, model.index 101 MB (veri fazla olduğu için), paylaşım zip'i 207 MB
  (`data/egitim/yasli_kadin/yasli_kadin-1.0.0.zip`). Index küçültme ileride, A/B ile.
- Kullanıcı arkadaşlarıyla test edecek.

## D49 — Release yapısı: tek kaynak, iki repo, sesler özelden (2026-10-05)
- Kullanıcı kararı:
  - GitHub'a sadece ses değiştirici uygulaması gider (kod + başlatıcı exe, Releases).
  - Eğitim kodu **ayrı bir repoya** gider; kendi arayüzlü exe'siyle, isteyen kendisi eğitir.
  - **Ses modellerini kullanıcı arkadaşlarına özelden gönderir**; uygulama zip'i içe aktarır.
  - Program boş gelir (içinde ses yok).
- Bu klasör (`Wichelberg_VoiceChanger`) çalışma alanı ve **tek kaynak** olarak aynen kalır.
  - `tools/export_repos.py` yönetilen dosyaları iki kardeş klasöre aynalar: `../Wichelberg_Uygulama`
    (voicechanger/, tests/, docs/, bat'lar, README) ve `../Wichelberg_SesEgitimi` (training/ + `training/_repo`
    şablonundan README/.gitignore).
  - Hedefteki .git, .venv, data/, models/, config/'a dokunmaz. Hedef yollar `config/export_repos.json`'da
    hatırlanır (eğitim reposu kullanıcı tarafından harici SSD'ye taşınacak: `--egitim <yol>`).
  - Kod sadece burada düzenlenir; hedefte elle yapılan değişiklik bir sonraki aktarımda silinir.
- Uygulama eğitimden bağımsız (eğitim kodu sadece yorumlarda geçiyor). Boş uygulama reposunda testler:
  31 geçti, modele ihtiyaç duyan 12 test atlandı.
- D11/D12'deki "katalogdan GitHub'dan indirme" bölümünün yerini alır: Ses Kütüphanesi indirme yapmaz, zip içe aktarır
  (sha256 + license/source denetimiyle). `voices/catalog.json` ve `tools/add_to_catalog.py` yapılmayacak.
- Faz sırası: R1 ayırma → R2 uygulama (sv-ttk tema, Basit/Gelişmiş görünüm, Ses Kütüphanesi, boş başlangıç,
  program içi hız testi, VB-Cable yönergesi) → R3 başlatıcı exe (ilk açılışta kurulum ekranı) → R4 eğitim exe'si.
  Her faz sonunda kullanıcı onayı.
- Otomatik güncelleme şimdilik yok (kullanıcı henüz karar vermedi). Güncelleme = yeni zip'i aynı klasöre açmak;
  sesler/ayarlar zip'te olmadığı için korunur.

## D50 — Ortak AI modelleri herkese açık Hugging Face deposunda (2026-10-05)
- Kullanıcı kararı: `contentvec.onnx` (ContentVec, content-vec-best, MIT; D17) ve `fcpe.onnx` (FCPE, MIT; D18)
  public bir HF deposuna konur; kurulum ekranı bunları sha256 doğrulamasıyla otomatik indirir.
- Bunlar kimsenin sesi değil, genel modeller; D31'deki "sesler herkese açık yayınlanmaz" kuralıyla çelişmez.
  Ses modelleri yine sadece özelden gider.
- **RMVPE public depoya konmaz** (lj1995 ağırlıklarında "yalnızca araştırma" notu var; D18). Uygulama zaten
  varsayılan olarak FCPE kullanıyor.
- Python için `uv` (MIT/Apache-2.0) kullanılır; Python ve önbellek program klasörüne iner, sisteme hiçbir şey kurulmaz.

## D51 — Eğitim exe'si: Common Voice + kendi kayıtları, rıza onayıyla (2026-10-05)
- Kullanıcı kararı: eğitim arayüzü iki veri kaynağına izin verir: Common Voice (herkes kendi MDC anahtarıyla ve
  şartları kabul ederek, D43) ve kullanıcının kendi ses klasörü.
- Kendi klasöründe "kayıtlar bana ait / sahibinin açık izni var" onayı ve `license` + `source` alanları zorunludur;
  bunlar olmadan paketlenmez (D13; uygulama da bu alanlar boşsa sesi yüklemez).
- Eğitim NVIDIA (CUDA) GPU ister; yoksa arayüz bunu açıkça söyler. Uygulamanın "CPU temel platform" kuralı
  eğitimi kapsamaz (eğitim ayrı ürün, D45).

## D52 — Paketleme: venv + gizli klasör; ayrı "sadece release" reposu (2026-10-05)
- Kullanıcı kararı: uygulama exe'si **küçük bir başlatıcıdır**. Kullanıcı exe'nin yanında sadece `Wichelberg.exe`
  görür; Python (uv ile), `.venv`, uygulama kodu (derlenmiş `.pyc`, `.py` kaynağı yok), ayarlar ve sesler
  Windows'ta gizli işaretli bir klasörde durur. İlk açılışta kurulum ekranı Python'u ve her paketi tek tek
  indirirken gösterir. Eğitim exe'si de aynı yapıda (torch exe'ye gömülemeyecek kadar büyük).
- Kullanıcı kararı: kaynak kod özel repoda kalır; arkadaşlar release zip'ini **ayrı bir "sadece release"
  reposundan** indirir (kod görünmez).
- Not (kullanıcıya söylendi): gizlemek koruma değildir; derlenmiş kod geri çözülebilir.

## D53 — R2: modern arayüz, Ses Kütüphanesi, program içi hız testi (2026-10-05)
- Tema: **sv-ttk 2.6.1** (MIT), açık/koyu; `ui.theme` = system (Windows ayarını izler) | light | dark.
  Tk 8.6.12'de sv-ttk'nin `<<ThemeChanged>>` olayı kök pencereye gelmiyor (arka planlar gri kalıyordu):
  `configure_colors` ve giriş kutusu yazı tipi elle çağrılıyor (`gui/theme.py`).
- Görünüm: `ui.view` = simple (varsayılan) | advanced. Basit: durum + Başlat + mod + ses/preset + cihazlar +
  seviye + Ses Kütüphanesi. Gelişmiş: + DSP slider paneli, Ses stüdyosu, ölçümler, AI ayarları, kısayol.
  Sekmeler kaydırılabilir (küçük laptop ekranları); pencere ilk açılışta ekrana sığdırılıp ortalanır.
- Ses Kütüphanesi (`ai/library.py`, `gui/library_panel.py`): zip veya klasör içe aktarma (sürükle-bırak:
  tkinterdnd2), önce bilgiler gösterilip onay istenir. Zip'te `..`/mutlak yol reddedilir. Dosyalar geçici
  klasöre çıkarılıp license/source + sha256 doğrulanır, sonra tek adımda yerine konur. Aynı id varsa ses önce
  motordan bırakılır (o an sessizlik), sonra değiştirilir. Gerçek `yasli_kadin` zip'i (207 MB) 0.3 sn'de kuruldu.
- Boş başlangıç: ses yoksa / ortak modeller eksikse / hız testi yoksa AI seçeneği kapalı; nedeni ve "Ses
  Kütüphanesi" / "Hız testi" düğmesi gösterilir. DSP her zaman çalışır.
- Hız testi programın içinden: `benchmark --json <dosya>` alt süreçte çalışır, `[ilerleme] i/n` satırları
  ilerleme çubuğuna gider. Sonucu program kendisi uygular (`apply_result`): program ile alt sürecin aynı anda
  config.json'a yazması önlenir. Canlı açıkken başlatılamaz; test sürerken canlı başlatılamaz; Durdur ve program
  kapanışı alt süreci sahte oyun süreçleriyle birlikte öldürür. Kısa test ile denendi (config değişmedi, RTX 5070
  ≈ 255 ms, D23 ile aynı).
- VB-Cable yoksa ana ekranda kart: indirme sayfası, kurulum adımları, "Tekrar kontrol et".
- Önizleme, Windows'un varsayılan çıkışı CABLE Input ise çalınmaz (Discord'a gitmesin).
- Canlı ses yolu değişmedi (D40): engine.py, ai/live.py, ai/rvc_onnx.py, ai/runtime.py, render.py, dsp/ R2
  öncesiyle birebir aynı (karşılaştırıldı). Testler: 53 (43 + kütüphane 8 + hız testi sonucu 2) geçti.
- Kaldırılan: `paths.CATALOG_FILE` (katalog yok, D49).

## D54 — R3: başlatıcı exe ve ilk açılış kurulumu (2026-10-05)
- `launcher/wichelberg.py` (arayüz) + `launcher/kurulum.py` (mantık, testli) → PyInstaller 6.22.3 (GPL, önyükleyici
  istisnasıyla dağıtılabilir) ile `Wichelberg.exe`. Derleme ortamı `data/build/venv` (uygulamanın .venv'i değil; D45
  ile aynı ilke). Derleme: `.venv\Scripts\python launcher\build_release.py` → `data/release/Wichelberg-<sürüm>.zip`
  (10.6 MB) + release reposu için `README.md` (`launcher/RELEASE_README.md`, arkadaşlar için).
- Yapı (D52): klasörde `Wichelberg.exe` + gizli `_wichelberg/` (uygulama kökü: voicechanger/*.pyc — `.py` kaynağı
  yok —, python/, .venv/, models/, config/, data/, başlatıcının kendi dosyaları). PyInstaller içerik klasörü tek
  düzey olmak zorunda olduğu için başlatıcı dosyaları da `_wichelberg/` içinde (çakışma yok, derlemede denetlenir).
- **uv kullanılmadı (D50'nin uv kısmının yerini alır):** uv'nin indirdiği Python paketinin aynısı
  (python-build-standalone 3.11.17, 24 MB) doğrudan indiriliyor. Böylece her dosya boyut/hız/kalan süreyle
  gösteriliyor, uv'nin Windows kayıt defterine Python kaydı / ~/.local/bin gibi sistem yan etkileri yok, zip'e
  40 MB'lık uv.exe girmiyor. Python ve her şey sadece `_wichelberg/` içine iner (kullanıcının isteği karşılanıyor).
- Paketler kilitli: derlemede requirements.txt → 20 hazır wheel (win_amd64/cp311; derleme gerekmez), her birinin
  PyPI adresi + sha256 + boyutu `kurulum.json`'a yazılır. Kurulum önce hepsini indirir (sha256 doğrulamalı,
  yarım kalan indirme kaldığı yerden sürer), sonra tek tek kurar. Ortak modeller aynı şekilde (adres: D50, HF).
- Akış: ilk açılışta kurulum ekranı (Python → paketler → ortak modeller → VB-Cable kontrolü; "Ayrıntıları göster"
  ile tam günlük); sonraki açılışlarda program doğrudan açılır ("açılıyor…" penceresi, program penceresi görününce
  kapanır). Program hatayla kapanırsa günlük gösterilir + "Onar" (kurulumu baştan yapar, sesler/ayarlar korunur).
  Program zaten açıksa ikinci kopya açılmaz, açık olan öne getirilir (iki kopya aynı anda CABLE'a yazmasın).
- Güncelleme: yeni zip aynı yere açılır; başlatıcı değişen paketleri kurar, yeni sürümde olmayan eski .pyc'leri
  siler, klasör taşındıysa .venv yolunu düzeltir. Model adresi yoksa adım atlanır (DSP çalışır), program açılır.
- Korumalar: Program Files gibi yazılamayan klasör ve **260 karakter yol sınırı** (.venv içindeki en uzun yol ~145
  karakter → `_wichelberg` yolu ≤ 100) için açık Türkçe uyarı; diskte yer denetimi; iptal.
- Test (gerçek indirme, yolunda boşluk + Türkçe karakter olan klasör): ilk kurulum **84 sn** (Python + 20 paket
  internetten, modeller yerel dosya adresiyle sha256 doğrulamalı), ikinci açılışta program 10 sn'de açıldı,
  klasör gizli, kurulum sonrası 971 MB. Release ortamında yaşlı kadın sesi içe aktarılıp CPU ve RTX 5070'te
  dönüştürüldü. Testler 61 (başlatıcı 8).
- Bulunan hatalar: (1) iş parçacığından arayüze hata iletilirken `except` bloğu bitince silinen `exc`'e erişiliyordu
  → arayüz donuyordu (başlatıcıda ve R2'nin Ses Kütüphanesi'nde; düzeltildi, olay döngüleri artık hatada durmuyor).
  (2) çok derin test klasöründe 260 karakter sınırı → yukarıdaki uyarı eklendi.
- Uygulamaya eklenen: sürüm (`voicechanger.__version__` = 1.0.0, başlıkta), pencere simgesi, kendi görev çubuğu kimliği.
- Açık: ortak modellerin HF adresi (D50) — kullanıcı hesabı açınca `shared.py` url'leri doldurulup yeniden derlenecek.
  İmzasız exe → SmartScreen uyarısı (README'de anlatıldı).

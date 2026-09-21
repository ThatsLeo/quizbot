import librosa
import numpy as np
import matplotlib.pyplot as plt
import subprocess
from pathlib import Path


def compute_chroma_flux(chroma):
    # Differenza frame-a-frame sulla dimensione armonica, poi sommata sulle 12 classi
    flux = np.sum(np.diff(chroma, axis=1) ** 2, axis=0)
    # Il primo frame non ha un "precedente": padding con 0 per allineare le lunghezze
    return np.concatenate([[0], flux])


def normalize(arr):
    arr = np.asarray(arr, dtype=float)
    min_v, max_v = arr.min(), arr.max()
    if max_v - min_v < 1e-8:
        return np.zeros_like(arr)
    return (arr - min_v) / (max_v - min_v)


def sampling_pipeline(track_path, hop_length=1024, window_sec=15,
                              w_centroid=0.5, w_rms=0.5, min_repetition=0.15):

    y, sr = librosa.load(track_path, mono=True)
    duration_sec = len(y) / sr

    window_frames = librosa.time_to_frames(window_sec, sr=sr, hop_length=hop_length)

    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=hop_length)
    chroma_smooth = librosa.decompose.nn_filter(chroma, aggregate=np.median, metric='cosine')
    S = librosa.segment.recurrence_matrix(chroma_smooth, mode='affinity', sym=True, k=None)

    rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
    centroid = librosa.feature.spectral_centroid(y=y, sr=sr, hop_length=hop_length)[0]

    rms_win = np.convolve(rms, np.ones(window_frames), mode='valid') / window_frames
    centroid_win = np.convolve(centroid, np.ones(window_frames), mode='valid') / window_frames

    rms_norm = normalize(rms_win)
    centroid_norm = normalize(centroid_win)
    base_score = w_rms * rms_norm + w_centroid * centroid_norm

    # Range di lag breve 
    min_lag_sec = max(duration_sec * 0.15, 15)
    max_lag_sec = min(duration_sec * 0.5, 60)
    min_lag_frames = librosa.time_to_frames(min_lag_sec, sr=sr, hop_length=hop_length)
    max_lag_frames = librosa.time_to_frames(max_lag_sec, sr=sr, hop_length=hop_length)

    best_repeated_score = -np.inf
    best_repeated_start = None

    for d in range(min_lag_frames, max_lag_frames):
        diag = np.diagonal(S, offset=d)
        if len(diag) < window_frames:
            continue
        sim_win = np.convolve(diag, np.ones(window_frames), mode='valid') / window_frames

        n = len(sim_win)
        eligible = sim_win >= min_repetition
        if not eligible.any():
            continue

        candidate = np.where(eligible, base_score[:n], -np.inf)
        idx = np.argmax(candidate)
        if candidate[idx] > best_repeated_score:
            best_repeated_score = candidate[idx]
            best_repeated_start = idx


    best_unconstrained_start = int(np.argmax(base_score))
    best_unconstrained_score = base_score[best_unconstrained_start]

    if best_repeated_start is not None and best_repeated_score >= best_unconstrained_score * 0.9:
        best_start = best_repeated_start
    else:
        best_start = best_unconstrained_start

    return librosa.frames_to_time(best_start, sr=sr, hop_length=hop_length)


def cut(input_path, start_sec, output_path, duration=15):
    subprocess.run([
        "ffmpeg",
        "-y",                      # sovrascrive output_path se esiste già
        "-ss", str(start_sec),     # punto di inizio
        "-t", str(duration),       # durata del taglio
        "-i", input_path,
        "-c", "copy",         # nessuna ricodifica, solo taglio (più veloce)
        output_path
    ], check=True, capture_output=True)
    return output_path




def create_video(thumbnail, sample, title_path, artist_path, output_path, duration=15):
    canvas_size = 1080
    cover_size = 700
 
    cover_left = (canvas_size - cover_size) // 2
    cover_bottom = (canvas_size - cover_size) // 2 + cover_size
 
    title_x = cover_left
    title_y = cover_bottom + 22
    artist_x = cover_left
    artist_y = cover_bottom + 68

    pad_top = 10
    pad_left = 6
 
    title_box_w = cover_size
    title_box_h = 70
    artist_box_w = cover_size
    artist_box_h = 54
 
    title_speed = 80    # pixel al secondo
    artist_speed = 60   # pixel al secondo, leggermente piu' lento (font piu' piccolo)
    gap = 45            # spazio (in pixel) tra la fine del testo e la sua ripetizione
 
    font_path = "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf"
    artist_font_path = "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf"
 
    # Effetto "nastro trasportatore": due copie identiche dello stesso testo,
    # distanziate di (text_w + gap). Mentre la prima copia esce dal bordo
    # sinistro, la seconda (che la seguiva a distanza fissa) la sostituisce
    # esattamente al suo posto, dando l'illusione di un loop continuo senza
    # interruzioni. Se il testo entra gia' nel box, resta fermo a x=0 e la
    # seconda copia viene spinta fuori dal canvas (mai visibile).
    def scroll_x_exprs(box_w, speed):
        period = f"(text_w+{gap})"
        clamped_t = f"min(t\\,{period}/{speed})"
        base = f"-mod({clamped_t}*{speed}\\,{period})"
        x1 = f"if(gt(text_w,{box_w}),{base}+{pad_left},{pad_left})"
        x2 = f"if(gt(text_w,{box_w}),{base}+{period}+{pad_left},{box_w}+99999)"
        return x1, x2
 
    title_x1, title_x2 = scroll_x_exprs(title_box_w, title_speed)
    artist_x1, artist_x2 = scroll_x_exprs(artist_box_w, artist_speed)
 
    filter_complex = (
        f"[0:v]scale=1200:1200,gblur=sigma=110,crop={canvas_size}:{canvas_size}[bg];"
        f"[0:v]scale={cover_size}:{cover_size}[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2[composed];"
 
        f"color=size={title_box_w}x{title_box_h}:color=black@0.0:duration={duration}[title_bg];"
        f"[title_bg]drawtext=textfile={title_path}:fontfile={font_path}:"
        f"fontsize=42:fontcolor=white:borderw=1:bordercolor=black:y={pad_top}:x='{title_x1}'[title_c1];"
        f"[title_c1]drawtext=textfile={title_path}:fontfile={font_path}:"
        f"fontsize=42:fontcolor=white:borderw=1:bordercolor=black:y={pad_top}:x='{title_x2}'[title_canvas];"
        f"[composed][title_canvas]overlay={title_x}:{title_y}[with_title];"
 
        f"color=size={artist_box_w}x{artist_box_h}:color=black@0.0:duration={duration}[artist_bg];"
        f"[artist_bg]drawtext=textfile={artist_path}:fontfile={artist_font_path}:"
        f"fontsize=32:fontcolor=white:borderw=0.6:bordercolor=black:y={pad_top}:x='{artist_x1}'[artist_c1];"
        f"[artist_c1]drawtext=textfile={artist_path}:fontfile={artist_font_path}:"
        f"fontsize=32:fontcolor=white:borderw=0.6:bordercolor=black:y={pad_top}:x='{artist_x2}'[artist_canvas];"
        f"[with_title][artist_canvas]overlay={artist_x}:{artist_y}[final]"
    )
 
    result = subprocess.run([
        "ffmpeg",
        "-y",
        "-loop", "1",
        "-i", str(thumbnail),
        "-i", str(sample),
        "-filter_complex", filter_complex,
        "-map", "[final]",
        "-map", "1:a",
        "-c:v", "libx264",
        "-c:a", "aac",
        "-pix_fmt", "yuv420p",
        "-t", str(duration),
        str(output_path)
    ], capture_output=True, text=True)
 
    if result.returncode != 0:
        print("FFMPEG STDERR:\n", result.stderr)
        raise RuntimeError("ffmpeg fallito, vedi log sopra")
 
    return output_path


def extract_audio_from_video(input_path, output_path):

    subprocess.run([
        "ffmpeg",
        "-y",                      # sovrascrive output_path se esiste già
        "-i", input_path,
        "-f", "mp3",               #formato in uscita
        "-ab", "192000",           #codifica, in questo caso 192Kbps
        "-vn", output_path,
    ], check=True, capture_output=True)
    return output_path


def _write_text_file(text, path):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)



def extract_sample(input_path, output_path, duration=15):

    best_start_sec = sampling_pipeline(input_path)
    cut(input_path, best_start_sec, output_path, duration=duration)
    return output_path

def is_sample(path):
    return "sample" in path


def extract_sample_list(path_list: list[tuple], choice_list, disc_persistant, duration=15):
    from scraper import get_samplepath
    keys = list(choice_list.keys())
    for i, (mp3, mp4) in enumerate(path_list):
        out = []
        best_start_sec = None

        if mp3 is None:
            mp3 = mp4[:-1] + "3"
            extract_audio_from_video(mp4, mp3)

        for format in (mp3, mp4):

            output_path = get_samplepath(format)

            if not output_path.exists():
                if best_start_sec is None:
                    best_start_sec = sampling_pipeline(mp3)
                cut(format, best_start_sec, output_path, duration=duration)

            out.append(str(output_path))

        if not disc_persistant:
            Path(mp3).unlink(missing_ok=True)
            Path(mp4).unlink(missing_ok=True)

        yield choice_list[keys[i]]
from collections import deque
from typing import Deque, Tuple, Sequence

import numpy as np

from .....common.preprocessing.spectrogram import transform
from .....config.preprocessing import spec as conf_spec


def stft_spectrogram_collate(
    data: Sequence[Tuple[str, np.ndarray,
                         int]], config: conf_spec.STFTSpecConfig
) -> Sequence[Tuple[str, np.ndarray, np.ndarray, np.ndarray, int]]:
    """Transfrom a batch of data from time domain signal to frequency domain signal

    Args:
        data (Sequence[Tuple[str, np.ndarray, int]]): (batch_size, ) The data from upstream sound wave dataset loader.
        config (conf_spec.MelSpecConfig): The configuration used to generate stft-spectrogram.

    Returns:
        ret_data (Sequence[Tuple[str, np.ndarray, np.ndarray, np.ndarray, int]]): (batch_size, ) The transformed dataset with each data point being a tuple of (filename, stft_spec, stft_freq, stft_time, label).
    """
    ret_data: Deque[Tuple[str, np.ndarray, np.ndarray, np.ndarray,
                          int]] = deque()
    for filename, sound_wave, label in data:
        stft_spec, stft_freq, stft_time = transform.transform_stft_spectrogram(
            sound_wave=sound_wave,
            sample_rate=config.sample_rate,
            n_fft=config.n_fft,
            window_size=config.window_size,
            hop_size=config.hop_size,
            apply_log=config.apply_log)
        ret_data.append((filename, stft_spec, stft_freq, stft_time, label))
    return ret_data


def mel_spectrogram_collate(
    data: Sequence[Tuple[str, np.ndarray,
                         int]], config: conf_spec.MelSpecConfig
) -> Sequence[Tuple[str, np.ndarray, np.ndarray, np.ndarray, int]]:
    """[summary]

    Args:
        data (Sequence[Tuple[str, np.ndarray, int]]): (batch_size, ) The data from upstream sound wave dataset loader.
        config (conf_spec.MelSpecConfig): The configuration used to generate mel-spectrogram.

    Returns:
        ret_data (Sequence[Tuple[str, np.ndarray, np.ndarray, np.ndarray, int]]): (batch_size, ) The transformed dataset with each data point being a tuple of (filename, mel_spec, mel_freq, mel_time, label).
    """
    ret_data: Deque[Tuple[str, np.ndarray, np.ndarray, np.ndarray,
                          int]] = deque()
    freq_max: float = config.freq_max if config.freq_max > 0.0 else config.sample_rate / 2.0
    for filename, sound_wave, label in data:
        mel_spec, mel_freq, mel_time = transform.transform_mel_spectrogram(
            sound_wave=sound_wave,
            sample_rate=config.sample_rate,
            n_fft=config.n_fft,
            n_mels=config.n_mels,
            freq_min=config.freq_min,
            freq_max=freq_max,
            window_size=config.window_size,
            hop_size=config.hop_size,
            apply_log=config.apply_log)
        ret_data.append((filename, mel_spec, mel_freq, mel_time, label))
    return ret_data

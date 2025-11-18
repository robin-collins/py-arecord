"""
VAD Configuration Recommender

Analyzes collected data to suggest optimal configuration parameters.
"""

import logging
from typing import Dict, List, Any, Tuple
import statistics

from vad_database import VADDatabase


class VADRecommender:
    """
    Analyzes VAD metrics to recommend optimal configuration values.

    Uses statistical analysis and heuristics to suggest:
    - noise_floor_threshold
    - silence_threshold
    - vad_aggressiveness
    - silence_duration_seconds
    """

    def __init__(self, db: VADDatabase):
        """Initialize recommender with database connection."""
        self.db = db
        self.logger = logging.getLogger(__name__)

    def generate_recommendations(self) -> Dict[str, Any]:
        """
        Analyze data and generate configuration recommendations.

        Returns:
            Dictionary with recommended values and explanations
        """
        self.logger.info("Generating configuration recommendations...")

        recommendations = {
            'noise_floor_threshold': self._recommend_noise_floor(),
            'silence_threshold': self._recommend_silence_threshold(),
            'vad_aggressiveness': self._recommend_aggressiveness(),
            'silence_duration_seconds': self._recommend_silence_duration(),
        }

        return recommendations

    def _recommend_noise_floor(self) -> Dict[str, Any]:
        """
        Recommend noise_floor_threshold based on RMS distribution.

        Strategy: Use percentile of RMS levels during silence periods.
        """
        # Query all metrics
        metrics = self.db.query_metrics(limit=50000)

        if not metrics:
            return {
                'value': None,
                'confidence': 'low',
                'reason': 'Insufficient data'
            }

        # Get RMS levels during silence
        silence_rms = [m['rms_level'] for m in metrics if not m['is_speech']]

        if not silence_rms:
            return {
                'value': None,
                'confidence': 'low',
                'reason': 'No silence periods detected'
            }

        # Calculate percentiles
        p50 = statistics.median(silence_rms)
        p75 = self._percentile(silence_rms, 75)
        p90 = self._percentile(silence_rms, 90)
        p95 = self._percentile(silence_rms, 95)

        # Recommendation: 90th percentile of silence RMS
        # This ensures we skip VAD processing for most silence while avoiding false negatives
        recommended_value = round(p90, 1)

        return {
            'value': recommended_value,
            'confidence': 'high',
            'reason': f'90th percentile of silence RMS levels',
            'analysis': {
                'silence_rms_median': round(p50, 2),
                'silence_rms_p75': round(p75, 2),
                'silence_rms_p90': round(p90, 2),
                'silence_rms_p95': round(p95, 2),
                'silence_samples': len(silence_rms)
            }
        }

    def _recommend_silence_threshold(self) -> Dict[str, Any]:
        """
        Recommend silence_threshold for RMS-only fallback.

        Strategy: Find threshold that separates speech from silence.
        """
        metrics = self.db.query_metrics(limit=50000)

        if not metrics:
            return {
                'value': None,
                'confidence': 'low',
                'reason': 'Insufficient data'
            }

        # Get RMS levels for speech and silence
        speech_rms = [m['rms_level'] for m in metrics if m['is_speech']]
        silence_rms = [m['rms_level'] for m in metrics if not m['is_speech']]

        if not speech_rms or not silence_rms:
            return {
                'value': None,
                'confidence': 'low',
                'reason': 'Insufficient speech/silence samples'
            }

        # Find optimal threshold between distributions
        silence_p95 = self._percentile(silence_rms, 95)
        speech_p5 = self._percentile(speech_rms, 5)

        # Threshold should be between 95th percentile of silence and 5th percentile of speech
        if silence_p95 < speech_p5:
            # Clear separation exists
            recommended_value = round((silence_p95 + speech_p5) / 2, 1)
            confidence = 'high'
            reason = 'Clear separation between speech and silence RMS distributions'
        else:
            # Overlap exists, use more conservative threshold
            recommended_value = round(statistics.median(silence_rms) * 1.5, 1)
            confidence = 'medium'
            reason = 'Some overlap in speech/silence distributions, using conservative value'

        return {
            'value': recommended_value,
            'confidence': confidence,
            'reason': reason,
            'analysis': {
                'silence_p95': round(silence_p95, 2),
                'speech_p5': round(speech_p5, 2),
                'separation': round(speech_p5 - silence_p95, 2)
            }
        }

    def _recommend_aggressiveness(self) -> Dict[str, Any]:
        """
        Recommend VAD aggressiveness level.

        Strategy: Analyze false positives in tagged periods.
        """
        # Query metrics with tags
        metrics = self.db.get_metrics_with_tags()

        if not metrics:
            return {
                'value': None,
                'confidence': 'low',
                'reason': 'No tagged data available for analysis'
            }

        # Analyze speech detection during different tagged conditions
        music_metrics = [m for m in metrics if 'music_playing' in m['active_tags']]
        ambient_metrics = [m for m in metrics if 'loud_ambient' in m['active_tags']]

        # Count false positives (non-speech detected as speech during music/ambient)
        music_false_positives = sum(1 for m in music_metrics if m['is_speech'])
        ambient_false_positives = sum(1 for m in ambient_metrics if m['is_speech'])

        total_music = len(music_metrics)
        total_ambient = len(ambient_metrics)

        music_fp_rate = music_false_positives / total_music if total_music > 0 else 0
        ambient_fp_rate = ambient_false_positives / total_ambient if total_ambient > 0 else 0

        # Recommendation logic
        if music_fp_rate > 0.3 or ambient_fp_rate > 0.3:
            # High false positive rate - recommend more aggressive
            recommended_value = 3
            confidence = 'high'
            reason = 'High false positive rate detected, more aggressive filtering needed'
        elif music_fp_rate > 0.15 or ambient_fp_rate > 0.15:
            # Moderate false positive rate
            recommended_value = 2
            confidence = 'medium'
            reason = 'Moderate false positive rate, balanced aggressiveness recommended'
        else:
            # Low false positive rate - can be lenient
            recommended_value = 1
            confidence = 'medium'
            reason = 'Low false positive rate, lenient aggressiveness suitable'

        return {
            'value': recommended_value,
            'confidence': confidence,
            'reason': reason,
            'analysis': {
                'music_false_positive_rate': round(music_fp_rate * 100, 2),
                'ambient_false_positive_rate': round(ambient_fp_rate * 100, 2),
                'music_samples': total_music,
                'ambient_samples': total_ambient
            }
        }

    def _recommend_silence_duration(self) -> Dict[str, Any]:
        """
        Recommend silence_duration_seconds based on natural pause patterns.

        Strategy: Analyze silence gaps during tagged speech periods.
        """
        # Query metrics during tagged speech periods
        metrics = self.db.get_metrics_with_tags()

        speaker_metrics = [
            m for m in metrics
            if 'one_speaker_close' in m['active_tags'] or 'two_speakers' in m['active_tags']
        ]

        if len(speaker_metrics) < 100:
            return {
                'value': None,
                'confidence': 'low',
                'reason': 'Insufficient tagged speech data'
            }

        # Find silence gaps during conversations
        silence_gaps = []
        current_gap_start = None

        for i, m in enumerate(speaker_metrics):
            if not m['is_speech']:
                # Start of silence
                if current_gap_start is None:
                    current_gap_start = m['timestamp']
            else:
                # End of silence
                if current_gap_start is not None:
                    gap_duration = m['timestamp'] - current_gap_start
                    silence_gaps.append(gap_duration)
                    current_gap_start = None

        if not silence_gaps:
            return {
                'value': None,
                'confidence': 'low',
                'reason': 'No silence gaps detected in tagged speech periods'
            }

        # Calculate percentiles of natural pauses
        p75 = self._percentile(silence_gaps, 75)
        p90 = self._percentile(silence_gaps, 90)
        p95 = self._percentile(silence_gaps, 95)

        # Recommendation: 95th percentile of natural pauses
        # This ensures most conversation pauses don't trigger recording stops
        recommended_value = round(p95, 1)

        # Clamp to reasonable range
        if recommended_value < 5.0:
            recommended_value = 5.0
            reason = 'Minimum 5 seconds to avoid premature stops'
        elif recommended_value > 30.0:
            recommended_value = 30.0
            reason = 'Maximum 30 seconds to avoid excessively long recordings'
        else:
            reason = f'95th percentile of natural pause durations during speech'

        return {
            'value': recommended_value,
            'confidence': 'high',
            'reason': reason,
            'analysis': {
                'pause_p75': round(p75, 2),
                'pause_p90': round(p90, 2),
                'pause_p95': round(p95, 2),
                'total_gaps_analyzed': len(silence_gaps)
            }
        }

    @staticmethod
    def _percentile(data: List[float], percentile: float) -> float:
        """Calculate percentile of data."""
        if not data:
            return 0.0
        sorted_data = sorted(data)
        index = int(len(sorted_data) * (percentile / 100.0))
        return sorted_data[min(index, len(sorted_data) - 1)]

    def print_recommendations(self, recommendations: Dict[str, Any]):
        """Print recommendations in formatted output."""
        print("\n" + "=" * 70)
        print("VAD CONFIGURATION RECOMMENDATIONS")
        print("=" * 70)

        for param, rec in recommendations.items():
            print(f"\n{param}:")

            if rec['value'] is not None:
                print(f"  Recommended: {rec['value']}")
                print(f"  Confidence: {rec['confidence']}")
                print(f"  Reason: {rec['reason']}")

                if 'analysis' in rec and rec['analysis']:
                    print(f"  Analysis:")
                    for key, value in rec['analysis'].items():
                        print(f"    {key}: {value}")
            else:
                print(f"  No recommendation available")
                print(f"  Reason: {rec['reason']}")

        print("\n" + "=" * 70)
        print("SUGGESTED CONFIG.INI CHANGES:")
        print("=" * 70)
        print("\n[audio]")

        for param, rec in recommendations.items():
            if rec['value'] is not None:
                # Format value appropriately
                if isinstance(rec['value'], float):
                    if param in ['noise_floor_threshold', 'silence_threshold']:
                        value_str = f"{rec['value']}"
                    else:
                        value_str = f"{rec['value']}"
                else:
                    value_str = str(rec['value'])

                print(f"{param} = {value_str}")

        print("\n" + "=" * 70)

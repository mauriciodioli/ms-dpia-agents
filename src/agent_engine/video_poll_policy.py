"""Bounded scheduling policy for read-only video status checks."""
from dataclasses import dataclass
from datetime import timedelta
import secrets


@dataclass(frozen=True)
class VideoPollPolicy:
    initial_seconds: int = 30
    maximum_seconds: int = 300
    max_checks: int = 240
    max_age_seconds: int = 86400
    jitter_percent: int = 20

    def __post_init__(self):
        if (not 10 <= self.initial_seconds <= 3600 or
                not self.initial_seconds <= self.maximum_seconds <= 3600 or
                not 1 <= self.max_checks <= 10000 or
                not self.initial_seconds <= self.max_age_seconds <= 604800 or
                not 0 <= self.jitter_percent <= 50):
            raise ValueError('invalid_video_poll_policy')

    @classmethod
    def from_config(cls, config):
        names={'initial_seconds':'AGENTS_VIDEO_POLL_INITIAL_SECONDS',
               'maximum_seconds':'AGENTS_VIDEO_POLL_MAXIMUM_SECONDS',
               'max_checks':'AGENTS_VIDEO_POLL_MAX_CHECKS',
               'max_age_seconds':'AGENTS_VIDEO_POLL_MAX_AGE_SECONDS',
               'jitter_percent':'AGENTS_VIDEO_POLL_JITTER_PERCENT'}
        values={}
        for field,key in names.items():
            if key in config:
                value=config[key]
                if isinstance(value,bool): raise ValueError('invalid_video_poll_policy')
                try: values[field]=int(value)
                except (ValueError,TypeError): raise ValueError('invalid_video_poll_policy') from None
        return cls(**values)

    def next_check(self, started_at, now, checks, *, random_below=secrets.randbelow):
        if type(checks) is not int or checks < 1: raise ValueError('invalid_video_poll_count')
        if checks >= self.max_checks or now >= started_at+timedelta(seconds=self.max_age_seconds):
            return None
        base=min(self.maximum_seconds,self.initial_seconds*(2**min(checks-1,20)))
        spread=base*self.jitter_percent//100
        delay=base+(random_below(2*spread+1)-spread if spread else 0)
        delay=max(self.initial_seconds,min(self.maximum_seconds,delay))
        due=now+timedelta(seconds=delay)
        return due if due < started_at+timedelta(seconds=self.max_age_seconds) else None

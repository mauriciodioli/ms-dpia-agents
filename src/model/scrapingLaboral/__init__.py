"""
Módulo de scraping laboral - Búsqueda, puntuación y aplicación de ofertas laborales.
"""

from .job_search import JobSearch
from .job_offer import JobOffer
from .job_search_result import JobSearchResult
from .cv_profile import CVProfile
from .cv_tailored import CVTailored
from .job_application import JobApplication

__all__ = [
    'JobSearch',
    'JobOffer',
    'JobSearchResult',
    'CVProfile',
    'CVTailored',
    'JobApplication'
]

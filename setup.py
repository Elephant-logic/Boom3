"""
Setup script for Boom3 Refactored
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read README
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text(encoding='utf-8')

setup(
    name="boom3-refactored",
    version="2.0.0",
    author="Boom3 Team",
    description="Production-ready AI app generator with modular architecture",
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        "openai>=1.3.5",
        "flask>=3.0.0",
        "flask-sock>=0.7.0",
        "pytest>=7.4.0",
        "requests>=2.31.0",
        "python-dotenv>=1.0.0",
    ],
    extras_require={
        "dev": [
            "pytest-asyncio>=0.21.0",
            "black>=23.0.0",
            "mypy>=1.0.0",
        ],
        "ui": [
            "ttkbootstrap>=1.10.1",
            "pillow>=10.0.0",
        ]
    },
    entry_points={
        "console_scripts": [
            "boom3=main:main",
            "boom3-web=ui.web_server:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Code Generators",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    include_package_data=True,
    package_data={
        "ui": ["templates/*.html", "static/*"],
    },
)

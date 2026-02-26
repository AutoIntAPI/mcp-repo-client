"""
Default patterns and configurations for repository scanning.
These mirror the patterns used in dependency-mapper-service and other services
that consume this package. Each service can override these by passing custom
values to MCPRepoProvider.
"""

FILE_EXTENSIONS = {
    'python': ['.py'],
    'javascript': ['.js', '.mjs', '.cjs', '.jsx'],
    'typescript': ['.ts', '.tsx', '.mts', '.cts'],
    'java': ['.java'],
    'php': ['.php', '.php5', '.php7', '.phtml'],
}

DEPENDENCY_FILES = {
    'python': ['requirements.txt', 'Pipfile', 'pyproject.toml', 'setup.py', 'poetry.lock'],
    'javascript': ['package.json', 'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml'],
    'typescript': [
        'tsconfig.json', 'package.json', 'package-lock.json',
        'yarn.lock', 'pnpm-lock.yaml', 'tsconfig.build.json', 'tsconfig.paths.json',
    ],
    'java': ['pom.xml', 'build.gradle', 'build.gradle.kts', 'gradle.properties'],
    'php': ['composer.json', 'composer.lock'],
}

IGNORE_DIRECTORIES = [
    'node_modules',
    'venv',
    '.venv',
    'env',
    '.env',
    '__pycache__',
    '.git',
    '.gradle',
    'target',
    'build',
    'dist',
    '.idea',
    '.vscode',
    'coverage',
    '.pytest_cache',
]

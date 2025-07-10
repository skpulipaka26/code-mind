"""
Dynamic language registry for scalable multi-language support.
Automatically discovers and loads available Tree-sitter parsers.
"""

import importlib
import pkgutil
from typing import Dict, List, Optional
from dataclasses import dataclass
from pathlib import Path

from tree_sitter import Language, Parser
from utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class LanguageConfig:
    """Configuration for a programming language."""
    name: str
    extensions: List[str]
    tree_sitter_module: str
    node_types: Dict[str, List[str]]  # Maps chunk types to Tree-sitter node types
    comment_patterns: List[str]
    string_patterns: List[str]
    lsp_language_id: Optional[str] = None
    
    
class LanguageRegistry:
    """Registry for dynamically discovering and managing language parsers."""
    
    def __init__(self):
        self.languages: Dict[str, LanguageConfig] = {}
        self.parsers: Dict[str, Parser] = {}
        self.extension_map: Dict[str, str] = {}
        self._discover_languages()
    
    def _discover_languages(self):
        """Automatically discover available Tree-sitter parsers."""
        # Built-in language configurations
        builtin_configs = {
            "python": LanguageConfig(
                name="python",
                extensions=[".py", ".pyi", ".pyw"],
                tree_sitter_module="tree_sitter_python",
                node_types={
                    "function": ["function_definition", "async_function_definition"],
                    "class": ["class_definition"],
                    "import": ["import_statement", "import_from_statement"],
                    "variable": ["assignment", "augmented_assignment"],
                },
                comment_patterns=["#"],
                string_patterns=['"""', "'''", '"', "'"],
                lsp_language_id="python"
            ),
            "javascript": LanguageConfig(
                name="javascript",
                extensions=[".js", ".jsx", ".mjs", ".cjs"],
                tree_sitter_module="tree_sitter_javascript",
                node_types={
                    "function": ["function_declaration", "function_expression", "arrow_function", "method_definition"],
                    "class": ["class_declaration"],
                    "import": ["import_statement", "export_statement"],
                    "variable": ["variable_declaration", "lexical_declaration"],
                },
                comment_patterns=["//", "/*"],
                string_patterns=['"', "'", "`"],
                lsp_language_id="javascript"
            ),
            "typescript": LanguageConfig(
                name="typescript",
                extensions=[".ts", ".tsx", ".d.ts"],
                tree_sitter_module="tree_sitter_typescript",
                node_types={
                    "function": ["function_declaration", "function_expression", "arrow_function", "method_definition"],
                    "class": ["class_declaration"],
                    "import": ["import_statement", "export_statement"],
                    "variable": ["variable_declaration", "lexical_declaration"],
                    "interface": ["interface_declaration"],
                    "type": ["type_alias_declaration"],
                },
                comment_patterns=["//", "/*"],
                string_patterns=['"', "'", "`"],
                lsp_language_id="typescript"
            ),
            "java": LanguageConfig(
                name="java",
                extensions=[".java"],
                tree_sitter_module="tree_sitter_java",
                node_types={
                    "function": ["method_declaration", "constructor_declaration"],
                    "class": ["class_declaration", "interface_declaration", "enum_declaration"],
                    "import": ["import_declaration", "package_declaration"],
                    "variable": ["variable_declarator", "field_declaration"],
                },
                comment_patterns=["//", "/*"],
                string_patterns=['"'],
                lsp_language_id="java"
            ),
            "rust": LanguageConfig(
                name="rust",
                extensions=[".rs"],
                tree_sitter_module="tree_sitter_rust",
                node_types={
                    "function": ["function_item"],
                    "class": ["struct_item", "enum_item", "trait_item", "impl_item"],
                    "import": ["use_declaration", "extern_crate_declaration"],
                    "variable": ["let_declaration"],
                },
                comment_patterns=["//", "/*"],
                string_patterns=['"', "'"],
                lsp_language_id="rust"
            ),
            "csharp": LanguageConfig(
                name="csharp",
                extensions=[".cs"],
                tree_sitter_module="tree_sitter_c_sharp",
                node_types={
                    "function": ["method_declaration", "constructor_declaration"],
                    "class": ["class_declaration", "interface_declaration", "struct_declaration", "enum_declaration"],
                    "import": ["using_directive"],
                    "variable": ["variable_declaration", "field_declaration"],
                },
                comment_patterns=["//", "/*"],
                string_patterns=['"', "'"],
                lsp_language_id="csharp"
            ),
            "go": LanguageConfig(
                name="go",
                extensions=[".go"],
                tree_sitter_module="tree_sitter_go",
                node_types={
                    "function": ["function_declaration", "method_declaration"],
                    "class": ["type_declaration"],
                    "import": ["import_declaration", "package_clause"],
                    "variable": ["var_declaration", "short_var_declaration"],
                },
                comment_patterns=["//", "/*"],
                string_patterns=['"', "'", "`"],
                lsp_language_id="go"
            ),
            "dart": LanguageConfig(
                name="dart",
                extensions=[".dart"],
                tree_sitter_module="tree_sitter_dart",
                node_types={
                    "function": ["function_signature", "method_signature"],
                    "class": ["class_definition"],
                    "import": ["import_specification", "library_name"],
                    "variable": ["initialized_variable_definition"],
                },
                comment_patterns=["//", "/*"],
                string_patterns=['"', "'"],
                lsp_language_id="dart"
            ),
            "ruby": LanguageConfig(
                name="ruby",
                extensions=[".rb"],
                tree_sitter_module="tree_sitter_ruby",
                node_types={
                    "function": ["method"],
                    "class": ["class", "module"],
                    "import": ["require", "load"],
                    "variable": ["assignment"],
                },
                comment_patterns=["#"],
                string_patterns=['"', "'"],
                lsp_language_id="ruby"
            ),
            "kotlin": LanguageConfig(
                name="kotlin",
                extensions=[".kt", ".kts"],
                tree_sitter_module="tree_sitter_kotlin",
                node_types={
                    "function": ["function_declaration"],
                    "class": ["class_declaration", "object_declaration", "interface_declaration"],
                    "import": ["import_header", "package_header"],
                    "variable": ["property_declaration"],
                },
                comment_patterns=["//", "/*"],
                string_patterns=['"', "'"],
                lsp_language_id="kotlin"
            ),
            "c": LanguageConfig(
                name="c",
                extensions=[".c", ".h"],
                tree_sitter_module="tree_sitter_c",
                node_types={
                    "function": ["function_definition", "function_declarator"],
                    "class": ["struct_specifier", "union_specifier"],
                    "import": ["preproc_include"],
                    "variable": ["declaration"],
                },
                comment_patterns=["//", "/*"],
                string_patterns=['"', "'"],
                lsp_language_id="c"
            ),
            "bash": LanguageConfig(
                name="bash",
                extensions=[".sh", ".bash"],
                tree_sitter_module="tree_sitter_bash",
                node_types={
                    "function": ["function_definition"],
                    "class": [],
                    "import": ["source_command"],
                    "variable": ["variable_assignment"],
                },
                comment_patterns=["#"],
                string_patterns=['"', "'"],
                lsp_language_id="bash"
            ),
            "scala": LanguageConfig(
                name="scala",
                extensions=[".scala"],
                tree_sitter_module="tree_sitter_scala",
                node_types={
                    "function": ["function_definition"],
                    "class": ["class_definition", "object_definition", "trait_definition"],
                    "import": ["import_declaration"],
                    "variable": ["val_definition", "var_definition"],
                },
                comment_patterns=["//", "/*"],
                string_patterns=['"', "'"],
                lsp_language_id="scala"
            ),
        }
        
        # Try to load each language
        for lang_name, config in builtin_configs.items():
            if self._try_load_language(config):
                self.languages[lang_name] = config
                # Map extensions to language
                for ext in config.extensions:
                    self.extension_map[ext] = lang_name
        
        # Add languages that don't have Tree-sitter parsers but have LSP support
        lsp_only_configs = {
            "kotlin": LanguageConfig(
                name="kotlin",
                extensions=[".kt", ".kts"],
                tree_sitter_module="tree_sitter_kotlin",  # May not exist
                node_types={
                    "function": ["function_declaration"],
                    "class": ["class_declaration", "object_declaration", "interface_declaration"],
                    "import": ["import_header", "package_header"],
                    "variable": ["property_declaration"],
                },
                comment_patterns=["//", "/*"],
                string_patterns=['"', "'"],
                lsp_language_id="kotlin"
            ),
            "csharp": LanguageConfig(
                name="csharp",
                extensions=[".cs"],
                tree_sitter_module="tree_sitter_c_sharp",  # May not exist
                node_types={
                    "function": ["method_declaration", "constructor_declaration"],
                    "class": ["class_declaration", "interface_declaration", "struct_declaration", "enum_declaration"],
                    "import": ["using_directive"],
                    "variable": ["variable_declaration", "field_declaration"],
                },
                comment_patterns=["//", "/*"],
                string_patterns=['"', "'"],
                lsp_language_id="csharp"
            ),
            "dart": LanguageConfig(
                name="dart",
                extensions=[".dart"],
                tree_sitter_module="tree_sitter_dart",  # May not exist
                node_types={
                    "function": ["function_signature", "method_signature"],
                    "class": ["class_definition"],
                    "import": ["import_specification", "library_name"],
                    "variable": ["initialized_variable_definition"],
                },
                comment_patterns=["//", "/*"],
                string_patterns=['"', "'"],
                lsp_language_id="dart"
            ),
        }
        
        # Add LSP-only languages (even without Tree-sitter parsers)
        for lang_name, config in lsp_only_configs.items():
            self.languages[lang_name] = config
            for ext in config.extensions:
                self.extension_map[ext] = lang_name
        
        # Auto-discover additional languages
        self._auto_discover_languages()
        
        # Add missing extensions for languages that failed to auto-discover
        self._add_missing_extensions()
    
    def _try_load_language(self, config: LanguageConfig) -> bool:
        """Try to load a Tree-sitter parser for a language."""
        try:
            module = importlib.import_module(config.tree_sitter_module)
            
            # Try different common API patterns
            language_func = None
            if hasattr(module, 'language'):
                language_func = module.language
            elif hasattr(module, f'language_{config.name}'):
                language_func = getattr(module, f'language_{config.name}')
            elif hasattr(module, f'{config.name}_language'):
                language_func = getattr(module, f'{config.name}_language')
            
            if language_func:
                try:
                    language = Language(language_func())
                    parser = Parser(language)
                    self.parsers[config.name] = parser
                    logger.info(f"Loaded {config.name} parser")
                    return True
                except Exception as version_error:
                    # Handle version compatibility issues
                    if "Incompatible Language version" in str(version_error):
                        logger.debug(f"Version incompatibility for {config.name}: {version_error}")
                        # Still register the language config for fallback chunking
                        return True
                    else:
                        raise version_error
            else:
                logger.warning(f"Could not find language function in {config.tree_sitter_module}")
                return False
                
        except ImportError:
            logger.debug(f"Tree-sitter parser for {config.name} not available")
            return False
        except Exception as e:
            logger.warning(f"Failed to load {config.name} parser: {e}")
            return False
    
    def _auto_discover_languages(self):
        """Auto-discover additional Tree-sitter parsers."""
        # Look for tree_sitter_* modules
        for finder, name, ispkg in pkgutil.iter_modules():
            if name.startswith('tree_sitter_') and name not in [
                'tree_sitter_python', 'tree_sitter_javascript', 'tree_sitter_typescript',
                'tree_sitter_java', 'tree_sitter_rust', 'tree_sitter_go', 'tree_sitter_ruby',
                'tree_sitter_csharp', 'tree_sitter_c_sharp', 'tree_sitter_dart', 'tree_sitter_kotlin',
                'tree_sitter_c', 'tree_sitter_bash', 'tree_sitter_scala'
            ]:
                lang_name = name.replace('tree_sitter_', '')
                
                # Create basic config for discovered language
                config = self._create_basic_config(lang_name, name)
                if config and self._try_load_language(config):
                    self.languages[lang_name] = config
                    for ext in config.extensions:
                        self.extension_map[ext] = lang_name
                    logger.info(f"Auto-discovered language: {lang_name}")
    
    def _add_missing_extensions(self):
        """Add missing extensions for languages that couldn't be auto-discovered."""
        # Manually add extensions for languages we know should be supported
        missing_mappings = {
            '.rs': 'rust',
            '.kt': 'kotlin', 
            '.kts': 'kotlin',
            '.cs': 'csharp',
            '.dart': 'dart',
            '.c': 'c',
            '.h': 'c',
            '.sh': 'bash',
            '.bash': 'bash',
            '.scala': 'scala'
        }
        
        for ext, lang in missing_mappings.items():
            if ext not in self.extension_map and lang in self.languages:
                self.extension_map[ext] = lang
                logger.debug(f"Added missing extension mapping: {ext} -> {lang}")
            elif ext not in self.extension_map:
                # Add even if language config failed to load (for fallback)
                self.extension_map[ext] = lang
                logger.debug(f"Added extension mapping for fallback: {ext} -> {lang}")
    
    def _create_basic_config(self, lang_name: str, module_name: str) -> Optional[LanguageConfig]:
        """Create a basic configuration for an auto-discovered language."""
        # Common extension patterns
        extension_map = {
            'c': ['.c', '.h'],
            'cpp': ['.cpp', '.cxx', '.cc', '.hpp', '.hxx'],
            'java': ['.java'],
            'go': ['.go'],
            'rust': ['.rs'],
            'ruby': ['.rb'],
            'php': ['.php'],
            'swift': ['.swift'],
            'kotlin': ['.kt', '.kts'],
            'scala': ['.scala'],
            'bash': ['.sh', '.bash'],
            'html': ['.html', '.htm'],
            'css': ['.css'],
            'json': ['.json'],
            'yaml': ['.yaml', '.yml'],
            'toml': ['.toml'],
            'xml': ['.xml'],
            'sql': ['.sql'],
            'dockerfile': ['Dockerfile', '.dockerfile'],
        }
        
        extensions = extension_map.get(lang_name, [f'.{lang_name}'])
        
        # Basic node types (common across many languages)
        basic_node_types = {
            "function": ["function_declaration", "function_definition", "method_declaration"],
            "class": ["class_declaration", "class_definition"],
            "import": ["import_statement", "include_statement", "use_statement"],
            "variable": ["variable_declaration", "assignment"],
        }
        
        return LanguageConfig(
            name=lang_name,
            extensions=extensions,
            tree_sitter_module=module_name,
            node_types=basic_node_types,
            comment_patterns=["//", "#", "/*"],  # Common comment patterns
            string_patterns=['"', "'"],  # Common string patterns
            lsp_language_id=lang_name
        )
    
    def get_language_for_file(self, file_path: str) -> Optional[str]:
        """Get the language for a file based on its extension."""
        path = Path(file_path)
        
        # Handle special cases
        if path.name in ['Dockerfile', 'dockerfile']:
            return 'dockerfile' if 'dockerfile' in self.languages else None
        
        # Check extensions
        ext = path.suffix.lower()
        return self.extension_map.get(ext)
    
    def get_parser(self, language: str) -> Optional[Parser]:
        """Get the Tree-sitter parser for a language."""
        return self.parsers.get(language)
    
    def get_config(self, language: str) -> Optional[LanguageConfig]:
        """Get the configuration for a language."""
        return self.languages.get(language)
    
    def get_supported_languages(self) -> List[str]:
        """Get list of supported languages."""
        return list(self.languages.keys())
    
    def get_supported_extensions(self) -> List[str]:
        """Get list of supported file extensions."""
        return list(self.extension_map.keys())
    
    def is_supported(self, language_or_extension: str) -> bool:
        """Check if a language or file extension is supported."""
        return (language_or_extension in self.languages or 
                language_or_extension in self.extension_map)


# Global registry instance
_registry = None

def get_language_registry() -> LanguageRegistry:
    """Get the global language registry instance."""
    global _registry
    if _registry is None:
        _registry = LanguageRegistry()
    return _registry
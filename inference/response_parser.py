import re
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum


class IssueSeverity(Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass
class ReviewIssue:
    """A single review issue/comment."""
    title: str
    description: str
    severity: IssueSeverity
    category: str
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    suggestion: Optional[str] = None


@dataclass
class ReviewSection:
    """A section of the review (e.g., Summary, Issues, etc.)."""
    title: str
    content: str
    issues: List[ReviewIssue]


@dataclass
class ParsedReview:
    """Structured review response."""
    summary: str
    sections: List[ReviewSection]
    total_issues: int
    severity_counts: Dict[IssueSeverity, int]
    overall_score: Optional[int] = None


class ResponseParser:
    """Parse LLM review responses into structured format."""
    
    def __init__(self):
        self.section_headers = [
            "summary", "issues found", "improvements", "best practices",
            "security", "performance", "critical issues", "medium issues",
            "minor issues", "recommendations", "bottlenecks", "optimizations"
        ]
        
        self.severity_keywords = {
            IssueSeverity.CRITICAL: ["critical", "severe", "major bug", "security flaw", "vulnerability"],
            IssueSeverity.HIGH: ["important", "significant", "high", "bug", "error", "problem"],
            IssueSeverity.MEDIUM: ["medium", "moderate", "improvement", "should", "consider"],
            IssueSeverity.LOW: ["minor", "low", "suggestion", "could", "might", "optional"],
            IssueSeverity.INFO: ["info", "note", "fyi", "informational"]
        }
    
    def parse_review(self, review_text: str) -> ParsedReview:
        """Parse review text into structured format."""
        # Extract overall score if present
        overall_score = self._extract_score(review_text)
        
        # Split into sections
        sections = self._extract_sections(review_text)
        
        # Extract summary
        summary = self._extract_summary(sections)
        
        # Parse issues from all sections
        all_issues = []
        parsed_sections = []
        
        for section_title, section_content in sections.items():
            issues = self._extract_issues_from_section(section_content, section_title)
            all_issues.extend(issues)
            
            parsed_section = ReviewSection(
                title=section_title,
                content=section_content,
                issues=issues
            )
            parsed_sections.append(parsed_section)
        
        # Count issues by severity
        severity_counts = {severity: 0 for severity in IssueSeverity}
        for issue in all_issues:
            severity_counts[issue.severity] += 1
        
        return ParsedReview(
            summary=summary,
            sections=parsed_sections,
            total_issues=len(all_issues),
            severity_counts=severity_counts,
            overall_score=overall_score
        )
    
    def _extract_score(self, text: str) -> Optional[int]:
        """Extract numerical score from text."""
        # Look for patterns like "Score: 8/10", "Security Score: 7", etc.
        score_patterns = [
            r"score[:\s]*(\d+)(?:/10)?",
            r"rating[:\s]*(\d+)(?:/10)?",
            r"(\d+)/10",
            r"(\d+)\s*out\s*of\s*10"
        ]
        
        for pattern in score_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                score = int(match.group(1))
                return min(max(score, 1), 10)  # Clamp between 1-10
        
        return None
    
    def _extract_sections(self, text: str) -> Dict[str, str]:
        """Extract sections from review text."""
        sections = {}
        
        # Split by markdown headers (## or **Section Name**)
        section_pattern = r'(?:^|\n)(?:##\s*|\*\*)(.*?)(?:\*\*)?(?:\s*:\s*|\s*\n)(.*?)(?=(?:\n##|\n\*\*|\Z))'
        matches = re.findall(section_pattern, text, re.DOTALL | re.MULTILINE)
        
        for title, content in matches:
            title = title.strip().lower()
            content = content.strip()
            
            # Map common section variations
            if any(header in title for header in self.section_headers):
                sections[title] = content
        
        # If no clear sections found, treat as single content
        if not sections:
            sections["general"] = text
        
        return sections
    
    def _extract_summary(self, sections: Dict[str, str]) -> str:
        """Extract summary from sections."""
        # Look for summary section first
        for title, content in sections.items():
            if "summary" in title or "overview" in title:
                return content[:500]  # Limit summary length
        
        # Fallback to first section or first paragraph
        if sections:
            first_content = next(iter(sections.values()))
            paragraphs = first_content.split('\n\n')
            return paragraphs[0][:500] if paragraphs else ""
        
        return "No summary available"
    
    def _extract_issues_from_section(self, content: str, section_title: str) -> List[ReviewIssue]:
        """Extract issues from a section."""
        issues = []
        
        # Split by bullet points or numbered lists
        issue_pattern = r'(?:^|\n)(?:[-*•]|\d+\.)\s*(.*?)(?=(?:\n[-*•]|\n\d+\.|\Z))'
        matches = re.findall(issue_pattern, content, re.DOTALL | re.MULTILINE)
        
        for match in matches:
            issue_text = match.strip()
            if len(issue_text) < 10:  # Skip very short items
                continue
            
            issue = self._parse_single_issue(issue_text, section_title)
            if issue:
                issues.append(issue)
        
        # If no bullet points found, treat lines as potential issues
        if not issues:
            lines = [line.strip() for line in content.split('\n') if line.strip()]
            for line in lines[:5]:  # Limit to first 5 lines
                if len(line) > 15:
                    issue = self._parse_single_issue(line, section_title)
                    if issue:
                        issues.append(issue)
        
        return issues
    
    def _parse_single_issue(self, issue_text: str, section_title: str) -> Optional[ReviewIssue]:
        """Parse a single issue from text."""
        if not issue_text or len(issue_text) < 10:
            return None
        
        # Extract file path and line number if present
        file_path, line_number = self._extract_location(issue_text)
        
        # Determine severity
        severity = self._determine_severity(issue_text, section_title)
        
        # Determine category from section title
        category = self._determine_category(section_title)
        
        # Split title and description
        lines = issue_text.split('\n', 1)
        title = lines[0][:100]  # Limit title length
        description = lines[1] if len(lines) > 1 else ""
        
        # Extract suggestion if present
        suggestion = self._extract_suggestion(issue_text)
        
        return ReviewIssue(
            title=title,
            description=description,
            severity=severity,
            category=category,
            file_path=file_path,
            line_number=line_number,
            suggestion=suggestion
        )
    
    def _extract_location(self, text: str) -> tuple[Optional[str], Optional[int]]:
        """Extract file path and line number from text."""
        # Look for patterns like "file.py:123" or "in file.py line 123"
        location_patterns = [
            r'([a-zA-Z0-9_/.-]+\.py):(\d+)',
            r'([a-zA-Z0-9_/.-]+\.js):(\d+)',
            r'([a-zA-Z0-9_/.-]+\.ts):(\d+)',
            r'in\s+([a-zA-Z0-9_/.-]+\.[a-z]+)\s+line\s+(\d+)',
            r'line\s+(\d+)\s+in\s+([a-zA-Z0-9_/.-]+\.[a-z]+)'
        ]
        
        for pattern in location_patterns:
            match = re.search(pattern, text)
            if match:
                groups = match.groups()
                if len(groups) == 2:
                    if groups[0].isdigit():  # line number first
                        return groups[1], int(groups[0])
                    else:  # file path first
                        return groups[0], int(groups[1])
        
        return None, None
    
    def _determine_severity(self, text: str, section_title: str) -> IssueSeverity:
        """Determine issue severity."""
        text_lower = text.lower()
        section_lower = section_title.lower()
        
        # Check section-based severity first
        if "critical" in section_lower:
            return IssueSeverity.CRITICAL
        elif "high" in section_lower or "major" in section_lower:
            return IssueSeverity.HIGH
        elif "medium" in section_lower or "moderate" in section_lower:
            return IssueSeverity.MEDIUM
        elif "minor" in section_lower or "low" in section_lower:
            return IssueSeverity.LOW
        
        # Check content-based severity
        for severity, keywords in self.severity_keywords.items():
            if any(keyword in text_lower for keyword in keywords):
                return severity
        
        # Default based on section type
        if "security" in section_lower:
            return IssueSeverity.HIGH
        elif "performance" in section_lower:
            return IssueSeverity.MEDIUM
        elif "improvement" in section_lower:
            return IssueSeverity.LOW
        
        return IssueSeverity.MEDIUM
    
    def _determine_category(self, section_title: str) -> str:
        """Determine issue category from section title."""
        section_lower = section_title.lower()
        
        if "security" in section_lower:
            return "Security"
        elif "performance" in section_lower:
            return "Performance"
        elif "bug" in section_lower or "issue" in section_lower:
            return "Bug"
        elif "improvement" in section_lower or "quality" in section_lower:
            return "Code Quality"
        elif "best practice" in section_lower or "convention" in section_lower:
            return "Best Practice"
        else:
            return "General"
    
    def _extract_suggestion(self, text: str) -> Optional[str]:
        """Extract suggestion or fix from issue text."""
        # Look for patterns like "Suggestion:", "Fix:", "Consider:", etc.
        suggestion_patterns = [
            r'suggestion[:\s]+(.*?)(?:\n|$)',
            r'fix[:\s]+(.*?)(?:\n|$)',
            r'consider[:\s]+(.*?)(?:\n|$)',
            r'recommend[:\s]+(.*?)(?:\n|$)',
            r'should[:\s]+(.*?)(?:\n|$)'
        ]
        
        for pattern in suggestion_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        
        return None
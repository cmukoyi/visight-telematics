import 'package:flutter/material.dart';

/// Breakpoints used throughout the app.
class AppBreakpoints {
  AppBreakpoints._();

  /// Compact / phone (< 600px)
  static const double mobile = 600;

  /// Medium / tablet (600–1024px)
  static const double tablet = 1024;

  /// Expanded / desktop (> 1024px)
  static const double desktop = 1024;
}

/// Which layout bucket the current screen falls into.
enum ScreenSize { mobile, tablet, desktop }

/// Provides the current [ScreenSize] and useful helpers for responsive layout.
///
/// ```dart
/// final layout = AppLayout.of(context);
/// if (layout.isMobile) { ... }
/// ```
class AppLayout {
  const AppLayout._(this.size, this.width, this.height);

  final ScreenSize size;
  final double width;
  final double height;

  bool get isMobile => size == ScreenSize.mobile;
  bool get isTablet => size == ScreenSize.tablet;
  bool get isDesktop => size == ScreenSize.desktop;
  bool get isTabletOrLarger => size != ScreenSize.mobile;

  /// Number of columns for a responsive grid (2 on tablet, 3+ on desktop).
  int get gridColumns {
    if (isDesktop) return 3;
    if (isTablet) return 2;
    return 1;
  }

  /// Horizontal page padding — tighter on mobile, generous on desktop.
  double get pagePadding {
    if (isDesktop) return 48;
    if (isTablet) return 32;
    return 16;
  }

  /// Max content width — caps the layout on wide screens.
  double get maxContentWidth {
    if (isDesktop) return 1200;
    if (isTablet) return 800;
    return double.infinity;
  }

  static AppLayout of(BuildContext context) {
    final size = MediaQuery.sizeOf(context);
    final w = size.width;
    ScreenSize screenSize;
    if (w >= AppBreakpoints.desktop) {
      screenSize = ScreenSize.desktop;
    } else if (w >= AppBreakpoints.mobile) {
      screenSize = ScreenSize.tablet;
    } else {
      screenSize = ScreenSize.mobile;
    }
    return AppLayout._(screenSize, w, size.height);
  }
}

/// Builds different widgets depending on screen size.
///
/// Only provide builders for the sizes you need — falls back to [mobile].
///
/// ```dart
/// ResponsiveBuilder(
///   mobile: (context) => BottomNavLayout(),
///   tablet: (context) => RailNavLayout(),
///   desktop: (context) => SidebarLayout(),
/// )
/// ```
class ResponsiveBuilder extends StatelessWidget {
  const ResponsiveBuilder({
    super.key,
    required this.mobile,
    this.tablet,
    this.desktop,
  });

  final WidgetBuilder mobile;
  final WidgetBuilder? tablet;
  final WidgetBuilder? desktop;

  @override
  Widget build(BuildContext context) {
    final layout = AppLayout.of(context);
    if (layout.isDesktop && desktop != null) return desktop!(context);
    if (layout.isTabletOrLarger && tablet != null) return tablet!(context);
    return mobile(context);
  }
}

/// A constrained page body that centres and pads content responsively.
///
/// Wrap your screen's main content in this to get consistent page margins
/// and a max-width cap on large screens without any extra code.
///
/// ```dart
/// ResponsivePage(
///   child: Column(children: [...]),
/// )
/// ```
class ResponsivePage extends StatelessWidget {
  const ResponsivePage({
    super.key,
    required this.child,
    this.scrollable = true,
    this.topPadding,
    this.bottomPadding,
  });

  final Widget child;
  final bool scrollable;
  final double? topPadding;
  final double? bottomPadding;

  @override
  Widget build(BuildContext context) {
    final layout = AppLayout.of(context);
    final padding = EdgeInsets.symmetric(horizontal: layout.pagePadding).copyWith(
      top: topPadding ?? 16,
      bottom: bottomPadding ?? 24,
    );

    Widget content = Center(
      child: ConstrainedBox(
        constraints: BoxConstraints(maxWidth: layout.maxContentWidth),
        child: Padding(
          padding: padding,
          child: child,
        ),
      ),
    );

    if (scrollable) {
      content = SingleChildScrollView(child: content);
    }

    return content;
  }
}

/// A responsive grid that automatically adjusts column count.
///
/// ```dart
/// ResponsiveGrid(
///   children: tags.map((t) => TagCard(t)).toList(),
/// )
/// ```
class ResponsiveGrid extends StatelessWidget {
  const ResponsiveGrid({
    super.key,
    required this.children,
    this.mobileColumns = 1,
    this.tabletColumns = 2,
    this.desktopColumns = 3,
    this.spacing = 16,
    this.runSpacing = 16,
  });

  final List<Widget> children;
  final int mobileColumns;
  final int tabletColumns;
  final int desktopColumns;
  final double spacing;
  final double runSpacing;

  @override
  Widget build(BuildContext context) {
    final layout = AppLayout.of(context);
    final cols = layout.isDesktop
        ? desktopColumns
        : layout.isTablet
            ? tabletColumns
            : mobileColumns;

    return LayoutBuilder(
      builder: (context, constraints) {
        final itemWidth =
            (constraints.maxWidth - (spacing * (cols - 1))) / cols;
        return Wrap(
          spacing: spacing,
          runSpacing: runSpacing,
          children: children.map((child) {
            return SizedBox(width: itemWidth, child: child);
          }).toList(),
        );
      },
    );
  }
}
